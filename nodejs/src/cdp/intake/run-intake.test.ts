import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'

import { HOG_INVOCATION_RESULTS_OUTPUT } from '~/common/outputs'
import { createRecordingIngestionOutputs } from '~/tests/helpers/recording-ingestion-outputs'

import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import { createExampleHogFlowInvocation } from '../_tests/fixtures-hogflows'
import {
    HogInvocationResultsService,
    HogInvocationResultsServiceOutput,
} from '../services/monitoring/hog-invocation-results.service'
import { Run, RunIntake, keyedRunId } from './run-intake'

describe('RunIntake', () => {
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
