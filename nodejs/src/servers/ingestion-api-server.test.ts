import { Counter, Gauge, register } from 'prom-client'

import { GROUPS_OUTPUT } from '~/common/outputs'
import { GroupFlushResult } from '~/ingestion/common/groups/group-store.interface'

import { IngestBatchResponse, SerializedKafkaMessage } from '../ingestion/api/types'
import { CleanupResources } from './base-server'
import { HttpIngestPump } from './http-ingest-pump'
import { IngestionApiServer } from './ingestion-api-server'

type Completion = { batchContext: { httpBatchSeq: number }; elements: unknown[]; sideEffects: Promise<unknown>[] }
type Delivery = { completion: Completion } | { error: Error }

/**
 * Stands in for the batching pipeline: records the sequence number fed with
 * each batch and lets a test complete (or crash) batches in any order, the
 * way the real pipeline returns completions in completion order.
 */
class FakePipeline {
    readonly seqs: number[] = []
    private parkedNext: { resolve: (c: Completion) => void; reject: (e: Error) => void } | null = null
    private queued: Delivery[] = []

    feed = jest.fn((_batch: unknown, context: { httpBatchSeq: number }): Promise<{ ok: true }> => {
        this.seqs.push(context.httpBatchSeq)
        return Promise.resolve({ ok: true })
    })

    next = jest.fn((): Promise<Completion> => {
        const queued = this.queued.shift()
        if (queued) {
            return 'error' in queued ? Promise.reject(queued.error) : Promise.resolve(queued.completion)
        }
        return new Promise((resolve, reject) => {
            this.parkedNext = { resolve, reject }
        })
    })

    complete(index: number, sideEffects: Promise<unknown>[] = []): void {
        this.deliver({ completion: { batchContext: { httpBatchSeq: this.seqs[index] }, elements: [], sideEffects } })
    }

    crash(error: Error): void {
        this.deliver({ error })
    }

    private deliver(delivery: Delivery): void {
        if (!this.parkedNext) {
            this.queued.push(delivery)
            return
        }
        const parked = this.parkedNext
        this.parkedNext = null
        if ('error' in delivery) {
            parked.reject(delivery.error)
        } else {
            parked.resolve(delivery.completion)
        }
    }
}

describe('IngestionApiServer', () => {
    let server: IngestionApiServer
    let pipeline: FakePipeline
    let stopSpy: jest.SpyInstance

    function makeMessage(): SerializedKafkaMessage {
        return { topic: 't', partition: 0, offset: 0, timestamp: 0, key: null, value: '{}', headers: {} }
    }

    function makeRes(): {
        status: (code: number) => { json: (body: IngestBatchResponse) => void }
        statusCode: () => number
        body: () => IngestBatchResponse
        responded: () => boolean
    } {
        const json = jest.fn()
        const status = jest.fn().mockReturnValue({ json })
        return {
            status,
            statusCode: () => status.mock.calls[0][0],
            body: () => json.mock.calls[0][0],
            responded: () => status.mock.calls.length > 0,
        }
    }

    function handle(res: ReturnType<typeof makeRes>, messageCount = 1): Promise<void> {
        const messages = Array.from({ length: messageCount }, makeMessage)
        const req = { body: { batch_id: 'b1', messages } }
        return (server as any).handleIngestRequest(req, res)
    }

    // Let pending callbacks run so a started request is fed and the pump is
    // waiting on next() before the test acts.
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

    function setup(concurrentBatches: number): void {
        server = new IngestionApiServer({ INGESTION_WORKER_CONCURRENT_BATCHES: concurrentBatches })
        pipeline = new FakePipeline()
        const promiseScheduler = { schedule: jest.fn(), waitForAll: jest.fn().mockResolvedValue(undefined) }
        ;(server as any).promiseScheduler = promiseScheduler
        ;(server as any).httpPump = new HttpIngestPump(pipeline as any, promiseScheduler as any, 1)
        ;(server as any).hogTransformer = { processInvocationResults: jest.fn().mockResolvedValue(undefined) }
        // stop() would call process.exit; stub it so the test only observes that it was invoked.
        stopSpy = jest.spyOn(server, 'stop').mockResolvedValue(undefined)
    }

    beforeEach(() => {
        setup(16)
        // The gauge is a module-level singleton shared across tests in this file.
        register.getSingleMetric('ingestion_api_events_in_flight')?.reset()
        register.getSingleMetric('ingestion_api_event_seconds_in_flight_total')?.reset()
    })

    afterEach(async () => {
        await (server as any).httpPump.stop()
    })

    it('reports healthy before any failure', () => {
        expect(isHealthy().status).toBe('ok')
    })

    it('crashes and rebuilds on an unexpected pipeline error', async () => {
        const res = makeRes()
        const req = handle(res)
        await flush()
        pipeline.crash(new Error('pipeline poisoned'))
        await req

        // Retriable 500 so the Rust consumer redelivers the batch.
        expect(res.statusCode()).toBe(500)
        expect(res.body()).toMatchObject({ status: 'error' })
        // Latched unhealthy and shut down so the supervisor rebuilds the pipeline.
        expect(isHealthy().status).toBe('error')
        expect(stopSpy).toHaveBeenCalledTimes(1)
    })

    it('returns 503 backpressure when the pipeline is at capacity, without crashing', async () => {
        pipeline.feed.mockResolvedValueOnce({
            ok: false,
            kind: 'at_capacity',
            reason: 'at concurrent batch capacity (1)',
        } as any)

        const res = makeRes()
        await handle(res)

        expect(res.statusCode()).toBe(503)
        expect(isHealthy().status).toBe('ok')
        expect(stopSpy).not.toHaveBeenCalled()
        expect(pipeline.next).not.toHaveBeenCalled()
    })

    it('processes a successful batch and stays healthy', async () => {
        const res = makeRes()
        const req = handle(res)
        await flush()
        pipeline.complete(0)
        await req

        expect(res.statusCode()).toBe(200)
        expect(res.body()).toMatchObject({ status: 'ok', accepted: 1 })
        expect(isHealthy().status).toBe('ok')
        expect(stopSpy).not.toHaveBeenCalled()
    })

    describe('per-batch completion', () => {
        it('responds to a batch as soon as it completes while others are still in flight', async () => {
            const [resA, resB, resC] = [makeRes(), makeRes(), makeRes()]
            const reqA = handle(resA)
            const reqB = handle(resB)
            const reqC = handle(resC)
            await flush()

            pipeline.complete(1)
            await reqB
            expect(resB.statusCode()).toBe(200)
            expect(resA.responded()).toBe(false)
            expect(resC.responded()).toBe(false)

            pipeline.complete(2)
            await reqC
            expect(resA.responded()).toBe(false)

            pipeline.complete(0)
            await reqA
            expect(resA.statusCode()).toBe(200)
        })

        it('responds only once the batch side effects have settled', async () => {
            let releaseSideEffect!: () => void
            const sideEffect = new Promise<void>((resolve) => {
                releaseSideEffect = resolve
            })
            const res = makeRes()
            const req = handle(res)
            await flush()

            pipeline.complete(0, [sideEffect])
            await flush()
            expect(res.responded()).toBe(false)

            releaseSideEffect()
            await req
            expect(res.statusCode()).toBe(200)
        })

        it('fails every in-flight batch when the pipeline crashes, and shuts down once', async () => {
            const [resA, resB] = [makeRes(), makeRes()]
            const reqA = handle(resA)
            const reqB = handle(resB)
            await flush()

            pipeline.crash(new Error('pipeline poisoned'))
            await Promise.all([reqA, reqB])

            expect(resA.statusCode()).toBe(500)
            expect(resB.statusCode()).toBe(500)
            expect(await eventsInFlight()).toBe(0)
            expect(stopSpy).toHaveBeenCalledTimes(1)
        })
    })

    describe('capacity at the door', () => {
        beforeEach(() => {
            setup(2)
        })

        it('rejects with 503 once accepted batches await a response, before feeding the pipeline', async () => {
            const first = start(1)
            const second = start(1)
            await flush()

            const rejected = makeRes()
            await handle(rejected)

            expect(rejected.statusCode()).toBe(503)
            expect(rejected.body()).toMatchObject({ status: 'error', accepted: 0 })
            expect(pipeline.feed).toHaveBeenCalledTimes(2)
            expect(isHealthy().status).toBe('ok')

            pipeline.complete(0)
            pipeline.complete(1)
            await Promise.all([first, second])
        })

        it('admits a batch again once one has responded', async () => {
            const first = start(1)
            const second = start(1)
            await flush()
            pipeline.complete(0)
            await first

            const res = makeRes()
            const third = handle(res)
            await flush()
            expect(pipeline.feed).toHaveBeenCalledTimes(3)

            pipeline.complete(1)
            pipeline.complete(2)
            await Promise.all([second, third])
            expect(res.statusCode()).toBe(200)
        })
    })

    describe('events in flight gauge', () => {
        it('sums events across concurrent batches of different sizes', async () => {
            const small = start(5)
            const medium = start(100)
            const large = start(1000)
            await flush()

            // 3 if it counted batches; the sum is the point of the metric.
            expect(await eventsInFlight()).toBe(1105)

            pipeline.complete(0)
            pipeline.complete(1)
            pipeline.complete(2)
            await Promise.all([small, medium, large])
            expect(await eventsInFlight()).toBe(0)
        })

        it('releases exactly the finished batch, leaving the others in flight', async () => {
            const first = start(100)
            const second = start(5)
            const third = start(20)
            await flush()
            expect(await eventsInFlight()).toBe(125)

            // Finish out of order: a decrement keyed to the wrong request would
            // subtract someone else's count and drift the gauge.
            pipeline.complete(1)
            await second
            expect(await eventsInFlight()).toBe(120)

            pipeline.complete(2)
            await third
            expect(await eventsInFlight()).toBe(100)

            pipeline.complete(0)
            await first
            expect(await eventsInFlight()).toBe(0)
        })

        it('leaves in-flight batches untouched when another is rejected at capacity', async () => {
            const accepted = start(100)
            await flush()

            pipeline.feed.mockResolvedValueOnce({ ok: false, kind: 'at_capacity', reason: 'at capacity' } as any)
            const rejectedRes = makeRes()
            await handle(rejectedRes, 50)

            expect(rejectedRes.statusCode()).toBe(503)
            expect(await eventsInFlight()).toBe(100)

            pipeline.complete(0)
            await accepted
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
                act: async () => {
                    const req = handle(makeRes(), 5)
                    await flush()
                    pipeline.complete(0)
                    await req
                },
            },
            {
                outcome: 'capacity rejection',
                act: async () => {
                    pipeline.feed.mockResolvedValueOnce({
                        ok: false,
                        kind: 'at_capacity',
                        reason: 'at capacity',
                    } as any)
                    await handle(makeRes(), 5)
                },
            },
            {
                outcome: 'pipeline crash',
                act: async () => {
                    const req = handle(makeRes(), 5)
                    await flush()
                    pipeline.crash(new Error('pipeline poisoned'))
                    await req
                },
            },
        ])('returns to zero after a $outcome', async ({ act }) => {
            await act()

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

        it('accumulates events multiplied by seconds in flight', async () => {
            clock.mockReturnValue(1_000)

            const batch = handle(makeRes(), 10)
            await flush()

            clock.mockReturnValue(3_500)
            pipeline.complete(0)
            await batch

            // 10 events held for 2.5s.
            expect(await eventSecondsInFlight()).toBe(25)
        })

        it('credits each concurrent batch its own duration', async () => {
            clock.mockReturnValue(0)

            const long = handle(makeRes(), 100)
            await flush()
            clock.mockReturnValue(1_000)
            const short = handle(makeRes(), 4)
            await flush()

            // short: accepted at 1s, ends at 3s  -> 4 * 2  =   8
            clock.mockReturnValue(3_000)
            pipeline.complete(1)
            await short
            expect(await eventSecondsInFlight()).toBe(8)

            // long: accepted at 0s, ends at 4s   -> 100 * 4 = 400
            clock.mockReturnValue(4_000)
            pipeline.complete(0)
            await long
            expect(await eventSecondsInFlight()).toBe(408)
        })

        it('recovers mean events in flight, which is the point of the counter', async () => {
            // One event held for 60s and 60 events each held for 1s both mean
            // "1 event in flight on average over a minute". A gauge scraped
            // once would report 1 or 60 depending on timing; the counter says
            // 60 event-seconds either way.
            clock.mockReturnValue(0)
            const steady = handle(makeRes(), 1)
            await flush()
            clock.mockReturnValue(60_000)
            pipeline.complete(0)
            await steady
            const heldLong = await eventSecondsInFlight()

            register.getSingleMetric('ingestion_api_event_seconds_in_flight_total')?.reset()

            for (let i = 0; i < 60; i++) {
                clock.mockReturnValue(i * 1_000)
                const burst = handle(makeRes(), 60)
                await flush()
                clock.mockReturnValue(i * 1_000 + 1_000)
                pipeline.complete(pipeline.seqs.length - 1)
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
            pipeline.feed.mockResolvedValueOnce({ ok: false, kind: 'at_capacity', reason: 'at capacity' } as any)

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
