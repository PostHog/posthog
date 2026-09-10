import { Counter, Gauge, register } from 'prom-client'

import { batchAccepted, batchReleased } from './batch-metrics'

describe('batch metrics', () => {
    let clock: jest.SpyInstance

    async function eventsInFlight(): Promise<number> {
        const gauge = register.getSingleMetric('ingestion_api_events_in_flight') as Gauge<string>
        const { values } = await gauge.get()
        return values[0]?.value ?? 0
    }

    async function eventSecondsInFlight(): Promise<number> {
        const counter = register.getSingleMetric('ingestion_api_event_seconds_in_flight_total') as Counter<string>
        const { values } = await counter.get()
        return values[0]?.value ?? 0
    }

    beforeEach(() => {
        clock = jest.spyOn(Date, 'now').mockReturnValue(0)
        register.getSingleMetric('ingestion_api_events_in_flight')?.reset()
        register.getSingleMetric('ingestion_api_event_seconds_in_flight_total')?.reset()
    })

    afterEach(() => {
        clock.mockRestore()
    })

    // The processor autoscaler reads events in flight: a count keyed to the
    // wrong batch, or a leaked increment, scales the fleet on phantom load.
    it('sums events across concurrent batches and releases exactly the finished batch', async () => {
        const first = batchAccepted(100)
        const second = batchAccepted(5)
        const third = batchAccepted(20)
        expect(await eventsInFlight()).toBe(125)

        batchReleased(second)
        expect(await eventsInFlight()).toBe(120)
        batchReleased(third)
        expect(await eventsInFlight()).toBe(100)
        batchReleased(first)
        expect(await eventsInFlight()).toBe(0)
    })

    // rate() over the counter must recover the time-weighted mean events in
    // flight, so each batch has to be credited its own events * duration.
    it('credits each batch its own event-seconds', async () => {
        const long = batchAccepted(100)
        clock.mockReturnValue(1_000)
        const short = batchAccepted(4)

        // short: accepted at 1s, released at 3s -> 4 * 2 = 8
        clock.mockReturnValue(3_000)
        batchReleased(short)
        expect(await eventSecondsInFlight()).toBe(8)

        // long: accepted at 0s, released at 4s -> 100 * 4 = 400
        clock.mockReturnValue(4_000)
        batchReleased(long)
        expect(await eventSecondsInFlight()).toBe(408)
    })
})
