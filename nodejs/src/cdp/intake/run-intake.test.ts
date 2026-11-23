import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'

import { HOG_INVOCATION_RESULTS_OUTPUT } from '~/common/outputs'
import { IngestionOutput } from '~/common/outputs/ingestion-output'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { createRecordingIngestionOutputs } from '~/tests/helpers/recording-ingestion-outputs'

import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import { createExampleHogFlowInvocation } from '../_tests/fixtures-hogflows'
import {
    CDP_INTAKE_MSK_TRANSACTIONAL_EMAIL_OUTPUT,
    CDP_INTAKE_MSK_WORKFLOW_WEBHOOK_OUTPUT,
    CDP_INTAKE_TRANSACTIONAL_EMAIL_OUTPUT,
    CDP_INTAKE_WORKFLOW_WEBHOOK_OUTPUT,
} from '../outputs/outputs'
import {
    HogInvocationResultsService,
    HogInvocationResultsServiceOutput,
} from '../services/monitoring/hog-invocation-results.service'
import {
    INTAKE_ACK_DEADLINE_MS,
    IntakeMode,
    IntakeOutput,
    IntakeProducer,
    PublishSettlement,
    publishesSettled,
} from './intake-producer'
import { Run, RunIntake, keyedRunId } from './run-intake'

describe('RunIntake', () => {
    afterEach(() => {
        jest.useRealTimers()
    })

    // A batch frees a recipient's slot on `publishesSettled()`, so a publish that outlives its ack deadline must still reach it.
    it.each(['async', 'shadow'] satisfies IntakeMode[])(
        'hands the settlement a %s publish that is still running after its ack deadline',
        async (mode) => {
            jest.useFakeTimers()
            let ack: () => void = () => {}
            const held: IngestionOutput = {
                produce: () => new Promise<void>((resolve) => (ack = resolve)),
                queueMessages: () => Promise.resolve(),
                checkHealth: () => Promise.resolve(),
                checkTopicExists: () => Promise.resolve(),
            }
            const producer = new IntakeProducer(
                new IngestionOutputs<IntakeOutput>({
                    [CDP_INTAKE_TRANSACTIONAL_EMAIL_OUTPUT]: held,
                    [CDP_INTAKE_WORKFLOW_WEBHOOK_OUTPUT]: held,
                    [CDP_INTAKE_MSK_TRANSACTIONAL_EMAIL_OUTPUT]: held,
                    [CDP_INTAKE_MSK_WORKFLOW_WEBHOOK_OUTPUT]: held,
                })
            )
            const intake = new RunIntake({
                hogflowQueue: createMockJobQueue(),
                invocationResultsRowsService: new HogInvocationResultsService(
                    createRecordingIngestionOutputs<HogInvocationResultsServiceOutput>([
                        HOG_INVOCATION_RESULTS_OUTPUT,
                    ]).outputs,
                    { HOG_INVOCATION_RESULTS_ENABLED: true }
                ),
                intake: { modeOf: () => mode, producer },
            })
            const hogFlow = new FixtureHogFlowBuilder().withTeamId(1).withSimpleWorkflow().build()
            const run: Run = {
                kind: 'transactional-email',
                invocation: createExampleHogFlowInvocation(hogFlow),
                claim: { fingerprint: 'request' },
            }
            const settlement = new PublishSettlement()
            let publishSettled = false

            const answered =
                mode === 'async'
                    ? intake.produce(run, settlement)
                    : intake.launch([run], { wait: 'committed', settlement })
            await jest.advanceTimersByTimeAsync(INTAKE_ACK_DEADLINE_MS)
            await answered
            void publishesSettled(settlement).then(() => (publishSettled = true))
            await jest.advanceTimersByTimeAsync(0)
            expect(publishSettled).toBe(false)

            ack()
            await jest.advanceTimersByTimeAsync(0)

            expect(publishSettled).toBe(true)
        }
    )

    describe('recallAllWithin', () => {
        const claims = [
            { runId: keyedRunId(1, 'transactional-email', 'a'), fingerprint: 'request-a' },
            { runId: keyedRunId(1, 'transactional-email', 'b'), fingerprint: 'request-b' },
            { runId: keyedRunId(1, 'transactional-email', 'c'), fingerprint: 'request-c' },
        ]
        const intakeOver = (findIdempotencyKeys: (runIds: string[]) => Promise<any>): RunIntake =>
            new RunIntake({
                hogflowQueue: { ...createMockJobQueue(), findIdempotencyKeys: jest.fn(findIdempotencyKeys) },
                invocationResultsRowsService: {} as HogInvocationResultsService,
            })

        it('answers each claim from its own row of one read', async () => {
            const rowsByRunId: Record<string, { fingerprint: string; reply: null }> = {
                [claims[1].runId]: { fingerprint: 'request-b', reply: null },
                [claims[2].runId]: { fingerprint: 'other', reply: null },
            }
            const intake = intakeOver((runIds) => Promise.resolve(runIds.map((runId) => rowsByRunId[runId] ?? null)))

            expect((await intake.recallAllWithin(claims, 'transactional-email')).map(({ status }) => status)).toEqual([
                'absent',
                'replayed',
                'mismatch',
            ])
        })

        it.each([
            ['hangs past its budget', () => new Promise(() => {})],
            ['fails', () => Promise.reject(new Error('connection refused'))],
        ])('reads every claim as absent when the read %s', async (_name, findIdempotencyKeys) => {
            jest.useFakeTimers()
            const recalled = intakeOver(findIdempotencyKeys).recallAllWithin(claims, 'transactional-email', 250)

            await jest.advanceTimersByTimeAsync(250)

            expect(await recalled).toEqual(claims.map(() => ({ status: 'absent' })))
        })
    })

    it('keeps the running row of a created run when a repeat of its key replays on the same pod', async () => {
        const kafka = createRecordingIngestionOutputs<HogInvocationResultsServiceOutput>([
            HOG_INVOCATION_RESULTS_OUTPUT,
        ])
        const rows = new HogInvocationResultsService(kafka.outputs, { HOG_INVOCATION_RESULTS_ENABLED: true })
        const intake = new RunIntake({ hogflowQueue: createMockJobQueue(), invocationResultsRowsService: rows })
        const hogFlow = new FixtureHogFlowBuilder().withTeamId(1).withSimpleWorkflow().build()
        const runId = keyedRunId(1, 'transactional-email', 'password-reset-1')
        const keyedRun = (): Run => {
            const invocation = createExampleHogFlowInvocation(hogFlow)
            invocation.id = runId
            return { kind: 'transactional-email', invocation, claim: { fingerprint: 'same-request' } }
        }

        const [first] = await intake.launch([keyedRun()], { wait: 'committed' })
        const [repeat] = await intake.launch([keyedRun()], { wait: 'committed' })
        await rows.flush()

        expect([first.outcome, repeat.outcome]).toEqual(['created', 'replayed'])
        expect(kafka.produced(HOG_INVOCATION_RESULTS_OUTPUT)).toEqual([
            expect.objectContaining({ invocation_id: runId, status: 'running' }),
        ])
    })

    it('versions the running row before a terminal row the run writes while its insert is still returning', async () => {
        const kafka = createRecordingIngestionOutputs<HogInvocationResultsServiceOutput>([
            HOG_INVOCATION_RESULTS_OUTPUT,
        ])
        const rows = new HogInvocationResultsService(kafka.outputs, { HOG_INVOCATION_RESULTS_ENABLED: true })
        const queue = createMockJobQueue()
        // The job is visible to workers once the claim commits, before the producer's await returns.
        const claim = queue.queueInvocationsIdempotently.getMockImplementation()!
        let returnFromInsert = (): void => {}
        const insertReturned = new Promise<void>((resolve) => (returnFromInsert = resolve))
        queue.queueInvocationsIdempotently.mockImplementation(async (entries) => {
            const outcomes = await claim.call(queue, entries)
            await insertReturned
            return outcomes
        })
        const intake = new RunIntake({ hogflowQueue: queue, invocationResultsRowsService: rows })
        const hogFlow = new FixtureHogFlowBuilder().withTeamId(1).withSimpleWorkflow().build()
        const invocation = createExampleHogFlowInvocation(hogFlow)
        invocation.id = keyedRunId(1, 'transactional-email', 'password-reset-2')

        const launched = intake.launch(
            [{ kind: 'transactional-email', invocation, claim: { fingerprint: 'request' } }],
            { wait: 'committed' }
        )
        rows.queueLifecycleRow(invocation, 'succeeded')
        returnFromInsert()
        await launched
        await rows.flush()

        const versionOf = (status: string): bigint =>
            BigInt(kafka.produced(HOG_INVOCATION_RESULTS_OUTPUT).find((row) => row.status === status)!.version)
        expect(versionOf('running')).toBeLessThan(versionOf('succeeded'))
    })
})
