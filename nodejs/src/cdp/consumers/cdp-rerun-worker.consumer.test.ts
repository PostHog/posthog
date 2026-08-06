import { DateTime } from 'luxon'

import { closeHub, createHub } from '~/common/utils/db/hub'
import { parseJSON } from '~/common/utils/json-parse'

import { createCdpConsumerDeps } from '../../../tests/helpers/cdp'
import { resetTestDatabase } from '../../../tests/helpers/sql'
import { Hub } from '../../types'
import { RERUN_QUEUE_NAME, RerunJobState } from '../rerun/rerun-job.types'
import { RerunJobQueues } from '../rerun/rerun-paginator.service'
import { CyclotronV2DequeuedJob } from '../services/cyclotron-v2/types'
import { CdpRerunWorkerConsumer } from './cdp-rerun-worker.consumer'

// Minimal stub for a job queue backend — the consumer only calls the producer
// lifecycle hooks; the paginator (which would call queueInvocations) is stubbed.
const buildMockJobQueues = (): RerunJobQueues => {
    const stub = () =>
        ({
            startAsProducer: jest.fn().mockResolvedValue(undefined),
            stopProducer: jest.fn().mockResolvedValue(undefined),
            queueInvocations: jest.fn().mockResolvedValue(undefined),
        }) as any
    return { hog_function: stub(), hog_flow: stub() }
}

jest.setTimeout(20000)

const buildDequeuedJob = (overrides: Partial<CyclotronV2DequeuedJob> = {}): jest.Mocked<CyclotronV2DequeuedJob> => {
    return {
        id: overrides.id ?? 'wrapper-job-1',
        teamId: overrides.teamId ?? 7,
        functionId: overrides.functionId ?? 'fn-1',
        queueName: RERUN_QUEUE_NAME,
        priority: 0,
        scheduled: DateTime.now(),
        created: DateTime.now(),
        parentRunId: null,
        transitionCount: 1,
        state: overrides.state ?? null,
        distinctId: null,
        personId: null,
        actionId: null,
        ack: jest.fn().mockResolvedValue(undefined),
        fail: jest.fn().mockResolvedValue(undefined),
        reschedule: jest.fn().mockResolvedValue(undefined),
        cancel: jest.fn().mockResolvedValue(undefined),
        heartbeat: jest.fn().mockResolvedValue(undefined),
    } as unknown as jest.Mocked<CyclotronV2DequeuedJob>
}

const buildState = (overrides: Partial<RerunJobState> = {}): RerunJobState => ({
    function_kind: 'hog_function',
    function_id: 'fn-1',
    request: {
        filter: {
            window_start: '2026-01-01T00:00:00Z',
            window_end: '2027-01-01T00:00:00Z',
            invocation_ids: ['inv-1'],
        },
    },
    progress: { queued: 0, skipped: 0, done: false },
    ...overrides,
})

const jobWithState = (state: RerunJobState): jest.Mocked<CyclotronV2DequeuedJob> =>
    buildDequeuedJob({ state: Buffer.from(JSON.stringify(state)) })

describe('CdpRerunWorkerConsumer', () => {
    let consumer: CdpRerunWorkerConsumer
    let hub: Hub
    let mockProcessPage: jest.Mock

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        // The worker needs the cyclotron-v2 node db to exist; pretend it does so the
        // consumer constructs cleanly. Real queue interactions are mocked below.
        hub.CYCLOTRON_NODE_DATABASE_URL = 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node'

        consumer = new CdpRerunWorkerConsumer(hub, createCdpConsumerDeps(hub), buildMockJobQueues())

        // Replace the paginator with a stub so we exercise the consumer's
        // ack/reschedule/fail decisions without hitting ClickHouse. The catch
        // path also calls `writeWrapperFailure` so the stub stubs that too.
        mockProcessPage = jest.fn()
        consumer['paginator'] = {
            processPage: mockProcessPage,
            writeWrapperFailure: jest.fn().mockResolvedValue(undefined),
        } as any

        // Don't start the real cyclotron worker loop — job queue producers are
        // already stubbed via buildMockJobQueues.
        consumer['worker'] = null
    })

    afterEach(async () => {
        // stop() touches the worker and cyclotron client; both are stubbed/null above.
        await consumer.stop().catch(() => undefined)
        await closeHub(hub)
    })

    describe('handleJob', () => {
        it('acks the wrapper job when the paginator returns done=true', async () => {
            const state = buildState()
            const job = jobWithState(state)
            mockProcessPage.mockResolvedValue({
                state: { ...state, progress: { ...state.progress, done: true, queued: 1 } },
            })

            await consumer['handleJob'](job)

            expect(job.ack).toHaveBeenCalledTimes(1)
            expect(job.reschedule).not.toHaveBeenCalled()
            expect(job.fail).not.toHaveBeenCalled()
        })

        it('reschedules the wrapper job with updated state when the paginator returns done=false', async () => {
            const state = buildState()
            const job = jobWithState(state)
            const nextState: RerunJobState = {
                ...state,
                progress: {
                    ...state.progress,
                    cursor: { scheduled_at: '2026-05-01 00:00:00.000000', invocation_id: 'last' },
                    queued: 200,
                    done: false,
                },
            }
            mockProcessPage.mockResolvedValue({ state: nextState })

            await consumer['handleJob'](job)

            expect(job.ack).not.toHaveBeenCalled()
            expect(job.fail).not.toHaveBeenCalled()
            expect(job.reschedule).toHaveBeenCalledTimes(1)
            const rescheduleArg = job.reschedule.mock.calls[0][0]!
            expect(rescheduleArg.scheduledAt).toBeInstanceOf(Date)
            // Persisted state matches the new state returned by the paginator.
            const persisted = parseJSON(rescheduleArg.state!.toString('utf8')) as RerunJobState
            expect(persisted.progress.queued).toBe(200)
            expect(persisted.progress.cursor).toEqual(nextState.progress.cursor)
        })

        it('fails the wrapper job when state JSON is malformed', async () => {
            const job = buildDequeuedJob({ state: Buffer.from('not-json{') })

            await consumer['handleJob'](job)

            expect(job.fail).toHaveBeenCalledTimes(1)
            expect(mockProcessPage).not.toHaveBeenCalled()
        })

        it('fails the wrapper job when state is missing entirely', async () => {
            const job = buildDequeuedJob({ state: null })

            await consumer['handleJob'](job)

            expect(job.fail).toHaveBeenCalledTimes(1)
            expect(mockProcessPage).not.toHaveBeenCalled()
        })

        it('fails the wrapper job when the paginator throws', async () => {
            const state = buildState()
            const job = jobWithState(state)
            mockProcessPage.mockRejectedValue(new Error('paginator exploded'))

            await consumer['handleJob'](job)

            expect(job.fail).toHaveBeenCalledTimes(1)
            expect(job.ack).not.toHaveBeenCalled()
            expect(job.reschedule).not.toHaveBeenCalled()
        })

        it('heartbeats during a long-running page so the cyclotron lock does not expire', async () => {
            jest.useFakeTimers()
            const state = buildState()
            const job = jobWithState(state)

            // Make processPage take long enough for two heartbeat ticks.
            mockProcessPage.mockImplementation(async () => {
                await new Promise<void>((resolve) => {
                    setTimeout(() => resolve(), 25_000)
                })
                return { state: { ...state, progress: { ...state.progress, done: true } } }
            })

            const handlePromise = consumer['handleJob'](job)
            await jest.advanceTimersByTimeAsync(25_000)
            await handlePromise

            expect(job.heartbeat).toHaveBeenCalled()
            expect(job.heartbeat.mock.calls.length).toBeGreaterThanOrEqual(2)
            jest.useRealTimers()
        })

        it('fails the job when the paginator field is unset (defensive guard)', async () => {
            consumer['paginator'] = null
            const state = buildState()
            const job = jobWithState(state)

            await consumer['handleJob'](job)

            expect(job.fail).toHaveBeenCalledTimes(1)
        })
    })

    describe('handleBatch', () => {
        it('drives every job in the batch through handleJob in order', async () => {
            const state = buildState()
            mockProcessPage.mockResolvedValue({ state: { ...state, progress: { ...state.progress, done: true } } })

            const jobs = [jobWithState(state), jobWithState({ ...state, function_id: 'fn-2' })]
            await consumer['handleBatch'](jobs)

            for (const job of jobs) {
                expect(job.ack).toHaveBeenCalledTimes(1)
            }
            expect(mockProcessPage).toHaveBeenCalledTimes(2)
        })
    })

    describe('isHealthy', () => {
        it('returns an error result when stopping', () => {
            consumer['isStopping'] = true
            expect(consumer.isHealthy().isError()).toBe(true)
        })

        it('returns an error result when the worker is missing', () => {
            consumer['isStopping'] = false
            consumer['worker'] = null
            expect(consumer.isHealthy().isError()).toBe(true)
        })
    })
})
