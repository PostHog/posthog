import { Counter, Gauge, register } from 'prom-client'

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

    async function eventSecondsInFlight(): Promise<number> {
        const counter = register.getSingleMetric('ingestion_api_event_seconds_in_flight_total') as Counter<string>
        const { values } = await counter.get()
        return values[0]?.value ?? 0
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
        ;(server as any).httpPipeline = pipeline
        ;(server as any).promiseScheduler = { schedule: jest.fn(), waitForAll: jest.fn().mockResolvedValue(undefined) }
        ;(server as any).hogTransformer = { processInvocationResults: jest.fn().mockResolvedValue(undefined) }
        // stop() would call process.exit; stub it so the test only observes that it was invoked.
        stopSpy = jest.spyOn(server, 'stop').mockResolvedValue(undefined)
        // The gauge is a module-level singleton shared across tests in this file.
        register.getSingleMetric('ingestion_api_events_in_flight')?.reset()
        register.getSingleMetric('ingestion_api_event_seconds_in_flight_total')?.reset()
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

    type Gate = { resolve: () => void; reject: (error: Error) => void }

    describe('events in flight gauge', () => {
        // One gate per in-flight batch. The handler calls next() exactly once
        // (the mock resolves to null, ending its drain loop), so holding that
        // promise open holds the batch in flight and lets a test decide the
        // order batches finish in.
        let gates: Gate[]

        beforeEach(() => {
            gates = []
        })

        function gateBatches(): void {
            pipeline.feed.mockResolvedValue({ ok: true })
            pipeline.next.mockImplementation(
                () =>
                    new Promise<null>((resolve, reject) => {
                        gates.push({ resolve: () => resolve(null), reject })
                    })
            )
        }

        // Let pending callbacks run so a started request reaches next() before
        // the test reads the gauge.
        function flush(): Promise<void> {
            return new Promise((resolve) => setImmediate(resolve))
        }

        // Starts a batch and returns its completion promise. Deliberately not
        // async: an async wrapper's promise would adopt this one, so awaiting
        // the helper would wait for the batch to finish instead of starting it.
        // Callers `await flush()` once the batches they want in flight are up.
        function start(messageCount: number): Promise<void> {
            return handle(makeRes(), messageCount)
        }

        it('sums events across concurrent batches of different sizes', async () => {
            gateBatches()

            const small = start(5)
            const medium = start(100)
            const large = start(1000)
            await flush()

            // 3 if it counted batches; the sum is the point of the metric.
            expect(await eventsInFlight()).toBe(1105)

            gates.forEach((gate) => gate.resolve())
            await Promise.all([small, medium, large])
            expect(await eventsInFlight()).toBe(0)
        })

        it('releases exactly the finished batch, leaving the others in flight', async () => {
            gateBatches()

            const first = start(100)
            const second = start(5)
            const third = start(20)
            await flush()
            expect(await eventsInFlight()).toBe(125)

            // Finish out of order: a decrement keyed to the wrong request would
            // subtract someone else's count and drift the gauge.
            gates[1].resolve()
            await second
            expect(await eventsInFlight()).toBe(120)

            gates[2].resolve()
            await third
            expect(await eventsInFlight()).toBe(100)

            gates[0].resolve()
            await first
            expect(await eventsInFlight()).toBe(0)
        })

        it('leaves in-flight batches untouched when another is rejected at capacity', async () => {
            gateBatches()
            const accepted = start(100)
            await flush()

            pipeline.feed.mockResolvedValueOnce({ ok: false, kind: 'at_capacity', reason: 'at capacity' })
            const rejectedRes = makeRes()
            await handle(rejectedRes, 50)

            expect(rejectedRes.statusCode()).toBe(503)
            expect(await eventsInFlight()).toBe(100)

            gates[0].resolve()
            await accepted
            expect(await eventsInFlight()).toBe(0)
        })

        it('releases a crashed batch while a concurrent batch stays in flight', async () => {
            gateBatches()
            const crashing = start(100)
            const surviving = start(7)
            await flush()

            gates[0].reject(new Error('pipeline poisoned'))
            await crashing
            expect(await eventsInFlight()).toBe(7)

            gates[1].resolve()
            await surviving
            expect(await eventsInFlight()).toBe(0)
        })

        it('does not count a batch rejected as empty', async () => {
            const res = makeRes()
            await handle(res, 0)

            expect(res.statusCode()).toBe(400)
            expect(await eventsInFlight()).toBe(0)
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

    describe('event-seconds counter', () => {
        // The counter is the integral of the gauge, so its whole value is that
        // rate() over it recovers mean events in flight without depending on
        // when a scrape lands. Driving Date.now directly keeps that arithmetic
        // exact and avoids faking the timers the request path runs on.
        let clock: jest.SpyInstance

        beforeEach(() => {
            clock = jest.spyOn(Date, 'now')
        })

        afterEach(() => {
            clock.mockRestore()
        })

        function gateBatches(): Gate[] {
            const gates: Gate[] = []
            pipeline.feed.mockResolvedValue({ ok: true })
            pipeline.next.mockImplementation(
                () =>
                    new Promise<null>((resolve, reject) => {
                        gates.push({ resolve: () => resolve(null), reject })
                    })
            )
            return gates
        }

        function flush(): Promise<void> {
            return new Promise((resolve) => setImmediate(resolve))
        }

        it('accumulates events multiplied by seconds in flight', async () => {
            const gates = gateBatches()
            clock.mockReturnValue(1_000)

            const batch = handle(makeRes(), 10)
            await flush()

            clock.mockReturnValue(3_500)
            gates[0].resolve()
            await batch

            // 10 events held for 2.5s.
            expect(await eventSecondsInFlight()).toBe(25)
        })

        it('credits each concurrent batch its own duration', async () => {
            const gates = gateBatches()
            clock.mockReturnValue(0)

            const long = handle(makeRes(), 100)
            await flush()
            clock.mockReturnValue(1_000)
            const short = handle(makeRes(), 4)
            await flush()

            // short: accepted at 1s, ends at 3s  -> 4 * 2  =   8
            clock.mockReturnValue(3_000)
            gates[1].resolve()
            await short
            expect(await eventSecondsInFlight()).toBe(8)

            // long: accepted at 0s, ends at 4s   -> 100 * 4 = 400
            clock.mockReturnValue(4_000)
            gates[0].resolve()
            await long
            expect(await eventSecondsInFlight()).toBe(408)
        })

        it('recovers mean events in flight, which is the point of the counter', async () => {
            // One event held for 60s and 60 events each held for 1s both mean
            // "1 event in flight on average over a minute". A gauge scraped
            // once would report 1 or 60 depending on timing; the counter says
            // 60 event-seconds either way.
            const gates = gateBatches()

            clock.mockReturnValue(0)
            const steady = handle(makeRes(), 1)
            await flush()
            clock.mockReturnValue(60_000)
            gates[0].resolve()
            await steady
            const heldLong = await eventSecondsInFlight()

            register.getSingleMetric('ingestion_api_event_seconds_in_flight_total')?.reset()

            for (let i = 0; i < 60; i++) {
                clock.mockReturnValue(i * 1_000)
                const burst = handle(makeRes(), 60)
                await flush()
                clock.mockReturnValue(i * 1_000 + 1_000)
                gates[gates.length - 1].resolve()
                await burst
            }
            const burstsShort = await eventSecondsInFlight()

            expect(heldLong).toBe(60)
            expect(burstsShort).toBe(3_600)
            // Same mean over their own window: 60/60s = 1, 3600/60s = 60.
            expect(heldLong / 60).toBe(1)
            expect(burstsShort / 60).toBe(60)
        })

        it('does not credit a batch rejected at capacity', async () => {
            clock.mockReturnValue(0)
            pipeline.feed.mockResolvedValue({ ok: false, kind: 'at_capacity', reason: 'at capacity' })

            clock.mockReturnValue(5_000)
            await handle(makeRes(), 10)

            expect(await eventSecondsInFlight()).toBe(0)
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
