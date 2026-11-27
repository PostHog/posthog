import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'

import { IngestionOutput } from '~/common/outputs/ingestion-output'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'

import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import { createExampleHogFlowInvocation } from '../_tests/fixtures-hogflows'
import { CDP_INTAKE_MSK_TRANSACTIONAL_EMAIL_OUTPUT, CDP_INTAKE_MSK_WORKFLOW_WEBHOOK_OUTPUT } from '../outputs/outputs'
import {
    INTAKE_ACK_DEADLINE_MS,
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
    it('hands the settlement a publish that is still running after its ack deadline', async () => {
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
                [CDP_INTAKE_MSK_TRANSACTIONAL_EMAIL_OUTPUT]: held,
                [CDP_INTAKE_MSK_WORKFLOW_WEBHOOK_OUTPUT]: held,
            })
        )
        const intake = new RunIntake({ hogflowQueue: createMockJobQueue(), producer })
        const hogFlow = new FixtureHogFlowBuilder().withTeamId(1).withSimpleWorkflow().build()
        const run: Run = {
            kind: 'transactional-email',
            invocation: createExampleHogFlowInvocation(hogFlow),
            claim: { fingerprint: 'request' },
        }
        const settlement = new PublishSettlement()
        let publishSettled = false

        const answered = intake.produce(run, settlement)
        await jest.advanceTimersByTimeAsync(INTAKE_ACK_DEADLINE_MS)
        await answered
        void publishesSettled(settlement).then(() => (publishSettled = true))
        await jest.advanceTimersByTimeAsync(0)
        expect(publishSettled).toBe(false)

        ack()
        await jest.advanceTimersByTimeAsync(0)

        expect(publishSettled).toBe(true)
    })

    describe('recallAllWithin', () => {
        const claims = [
            { runId: keyedRunId(1, 'transactional-email', 'a'), fingerprint: 'request-a' },
            { runId: keyedRunId(1, 'transactional-email', 'b'), fingerprint: 'request-b' },
            { runId: keyedRunId(1, 'transactional-email', 'c'), fingerprint: 'request-c' },
        ]
        const intakeOver = (findIdempotencyKeys: (runIds: string[]) => Promise<any>): RunIntake =>
            new RunIntake({
                hogflowQueue: { ...createMockJobQueue(), findIdempotencyKeys: jest.fn(findIdempotencyKeys) },
                producer: {} as IntakeProducer,
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
})
