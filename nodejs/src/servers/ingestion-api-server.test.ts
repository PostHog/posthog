import { Gauge, register } from 'prom-client'

import { GROUPS_OUTPUT } from '~/common/outputs'
import { GroupFlushResult } from '~/ingestion/common/groups/group-store.interface'

import { IngestBatchResponse, SerializedKafkaMessage } from '../ingestion/api/types'
import { CleanupResources } from './base-server'
import { IngestionApiServer } from './ingestion-api-server'

describe('IngestionApiServer', () => {
    let server: IngestionApiServer
    let pipeline: { feed: jest.Mock; next: jest.Mock }
    let stopSpy: jest.SpyInstance

    function makeMessage(): SerializedKafkaMessage {
        return { topic: 't', partition: 0, offset: 0, timestamp: 0, key: null, value: '{}', headers: {} }
    }

    function makeRes(): {
        status: (code: number) => { json: (body: IngestBatchResponse) => void }
        statusCode: () => number
        body: () => IngestBatchResponse
    } {
        const json = jest.fn()
        const status = jest.fn().mockReturnValue({ json })
        return {
            status,
            statusCode: () => status.mock.calls[0][0],
            body: () => json.mock.calls[0][0],
        }
    }

    function handle(res: ReturnType<typeof makeRes>, messageCount = 1): Promise<void> {
        const messages = Array.from({ length: messageCount }, makeMessage)
        const req = { body: { batch_id: 'b1', messages } }
        return (server as any).handleIngestRequest(req, res)
    }

    async function eventsInFlight(): Promise<number> {
        const gauge = register.getSingleMetric('ingestion_api_events_in_flight') as Gauge<string>
        const { values } = await gauge.get()
        return values[0]?.value ?? 0
    }

    function isHealthy(): { status: string } {
        return (server as any).isHealthy()
    }

    beforeEach(() => {
        server = new IngestionApiServer()
        pipeline = { feed: jest.fn(), next: jest.fn() }
        ;(server as any).joinedPipeline = pipeline
        ;(server as any).promiseScheduler = { schedule: jest.fn(), waitForAll: jest.fn().mockResolvedValue(undefined) }
        ;(server as any).hogTransformer = { processInvocationResults: jest.fn().mockResolvedValue(undefined) }
        // stop() would call process.exit; stub it so the test only observes that it was invoked.
        stopSpy = jest.spyOn(server, 'stop').mockResolvedValue(undefined)
        // The gauge is a module-level singleton shared across tests in this file.
        register.getSingleMetric('ingestion_api_events_in_flight')?.reset()
    })

    it('reports healthy before any failure', () => {
        expect(isHealthy().status).toBe('ok')
    })

    it('crashes and rebuilds on an unexpected pipeline error', async () => {
        pipeline.feed.mockResolvedValue({ ok: true })
        pipeline.next.mockRejectedValue(new Error('pipeline poisoned'))

        const res = makeRes()
        await handle(res)

        // Retriable 500 so the Rust consumer redelivers the batch.
        expect(res.statusCode()).toBe(500)
        expect(res.body()).toMatchObject({ status: 'error' })
        // Latched unhealthy and shut down so the supervisor rebuilds the pipeline.
        expect(isHealthy().status).toBe('error')
        expect(stopSpy).toHaveBeenCalledTimes(1)
    })

    it('returns 503 backpressure at capacity without crashing', async () => {
        pipeline.feed.mockResolvedValue({ ok: false, kind: 'at_capacity', reason: 'at concurrent batch capacity (1)' })

        const res = makeRes()
        await handle(res)

        expect(res.statusCode()).toBe(503)
        expect(isHealthy().status).toBe('ok')
        expect(stopSpy).not.toHaveBeenCalled()
        expect(pipeline.next).not.toHaveBeenCalled()
    })

    it('processes a successful batch and stays healthy', async () => {
        pipeline.feed.mockResolvedValue({ ok: true })
        pipeline.next.mockResolvedValue(null)

        const res = makeRes()
        await handle(res)

        expect(res.statusCode()).toBe(200)
        expect(res.body()).toMatchObject({ status: 'ok', accepted: 1 })
        expect(isHealthy().status).toBe('ok')
        expect(stopSpy).not.toHaveBeenCalled()
    })

    describe('events in flight gauge', () => {
        it('counts events rather than batches while a batch is in flight', async () => {
            let observed = 0
            pipeline.feed.mockResolvedValue({ ok: true })
            // next() runs while the batch occupies its slot, so this samples the peak.
            pipeline.next.mockImplementation(async () => {
                observed = await eventsInFlight()
                return null
            })

            await handle(makeRes(), 3)

            expect(observed).toBe(3)
        })

        // A leaked increment would make the gauge climb forever and, since this
        // drives processor autoscaling, scale the fleet out on phantom load.
        it.each([
            {
                outcome: 'success',
                arrange: () => {
                    pipeline.feed.mockResolvedValue({ ok: true })
                    pipeline.next.mockResolvedValue(null)
                },
            },
            {
                outcome: 'capacity rejection',
                arrange: () => {
                    pipeline.feed.mockResolvedValue({ ok: false, kind: 'at_capacity', reason: 'at capacity' })
                },
            },
            {
                outcome: 'pipeline crash',
                arrange: () => {
                    pipeline.feed.mockResolvedValue({ ok: true })
                    pipeline.next.mockRejectedValue(new Error('pipeline poisoned'))
                },
            },
        ])('returns to zero after a $outcome', async ({ arrange }) => {
            arrange()

            await handle(makeRes(), 5)

            expect(await eventsInFlight()).toBe(0)
        })
    })

    describe('cleanup', () => {
        // groupStore.flush() no longer produces ClickHouse messages itself (see
        // batch-writing-group-store.ts) — it returns them for the caller to
        // produce, mirroring personsStore.flushAndProduceMessages(). The shutdown
        // cleanup path must produce them itself or dirty entries flushed at
        // shutdown (e.g. a pod drain mid-batch) are written to Postgres but never
        // reach ClickHouse, and a redelivery of the same batch finds no property
        // diff and never regenerates the message.
        it('produces ClickHouse messages returned by groupStore.flush() during shutdown cleanup', async () => {
            const flushResult: GroupFlushResult = {
                messages: [{ output: GROUPS_OUTPUT, value: Buffer.from('group-payload') }],
                teamId: 1,
                groupTypeIndex: 0,
                groupKey: 'test-group',
            }
            const groupStore = {
                flush: jest.fn().mockResolvedValue([flushResult]),
                shutdown: jest.fn().mockResolvedValue(undefined),
            }
            const ingestionOutputs = { produce: jest.fn().mockResolvedValue(undefined) }
            ;(server as any).groupStore = groupStore
            ;(server as any).ingestionOutputs = ingestionOutputs

            const cleanup: CleanupResources = (server as any).getCleanupResources()
            await cleanup.additionalCleanup?.()

            expect(ingestionOutputs.produce).toHaveBeenCalledWith(GROUPS_OUTPUT, {
                key: null,
                value: flushResult.messages[0].value,
                teamId: flushResult.teamId,
            })
        })
    })
})
