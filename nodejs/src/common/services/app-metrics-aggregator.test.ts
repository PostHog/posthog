import { DateTime } from 'luxon'

import { APP_METRICS_OUTPUT, AppMetricsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { parseJSON } from '~/common/utils/json-parse'

import { AppMetricInput, AppMetricsAggregator, MAX_BUFFERED_ROWS } from './app-metrics-aggregator'

function makeOutputs(): {
    outputs: IngestionOutputs<AppMetricsOutput>
    queueMessagesMock: jest.Mock<Promise<void>, [any[]]>
} {
    const queueMessagesMock = jest.fn().mockResolvedValue(undefined)
    const fakeOutput = {
        produce: jest.fn().mockResolvedValue(undefined),
        queueMessages: queueMessagesMock,
        checkHealth: jest.fn().mockResolvedValue(undefined),
        checkTopicExists: jest.fn().mockResolvedValue(undefined),
    } as unknown as ConstructorParameters<typeof IngestionOutputs<AppMetricsOutput>>[0][AppMetricsOutput]
    return {
        outputs: new IngestionOutputs<AppMetricsOutput>({ [APP_METRICS_OUTPUT]: fakeOutput }),
        queueMessagesMock,
    }
}

function input(overrides: Partial<AppMetricInput> = {}): AppMetricInput {
    return {
        team_id: 1,
        app_source: 'hog_function',
        app_source_id: 'fn-1',
        instance_id: 'inst-1',
        metric_kind: 'success',
        metric_name: 'succeeded',
        count: 1,
        ...overrides,
    }
}

describe('AppMetricsAggregator', () => {
    let outputs: IngestionOutputs<AppMetricsOutput>
    let queueMessagesMock: jest.Mock<Promise<void>, [any[]]>

    beforeEach(() => {
        ;({ outputs, queueMessagesMock } = makeOutputs())
    })

    function getRows(callIndex = 0): Record<string, unknown>[] {
        const messages = queueMessagesMock.mock.calls[callIndex][0]
        return messages.map((m: { value: Buffer }) => parseJSON(m.value.toString()) as Record<string, unknown>)
    }

    it('flush is a no-op when nothing was queued', async () => {
        const agg = new AppMetricsAggregator(outputs)
        await agg.flush()
        expect(queueMessagesMock).not.toHaveBeenCalled()
    })

    it('serializes the v2 schema with all six identity fields, count, and a timestamp', async () => {
        const agg = new AppMetricsAggregator(outputs)
        agg.queue(input())
        await agg.flush()

        const row = getRows()[0]
        expect(row).toMatchObject({
            team_id: 1,
            app_source: 'hog_function',
            app_source_id: 'fn-1',
            instance_id: 'inst-1',
            metric_kind: 'success',
            metric_name: 'succeeded',
            count: 1,
        })
        expect(row.timestamp).toEqual(expect.any(String))
    })

    it('sums counts for entries sharing the six identity fields', async () => {
        const agg = new AppMetricsAggregator(outputs)
        agg.queue(input({ count: 1 }))
        agg.queue(input({ count: 2 }))
        agg.queue(input({ count: 4 }))
        await agg.flush()

        const rows = getRows()
        expect(rows).toHaveLength(1)
        expect(rows[0].count).toBe(7)
    })

    it.each([
        ['team_id', { team_id: 2 }],
        ['app_source', { app_source: 'hog_flow' }],
        ['app_source_id', { app_source_id: 'fn-2' }],
        ['instance_id', { instance_id: 'inst-2' }],
        ['metric_kind', { metric_kind: 'failure' }],
        ['metric_name', { metric_name: 'failed' }],
    ])('keeps %s separate', async (_field, override) => {
        const agg = new AppMetricsAggregator(outputs)
        agg.queue(input())
        agg.queue(input(override as Partial<AppMetricInput>))
        await agg.flush()

        expect(getRows()).toHaveLength(2)
    })

    it('treats undefined instance_id as ""', async () => {
        const agg = new AppMetricsAggregator(outputs)
        agg.queue(input({ instance_id: undefined }))
        agg.queue(input({ instance_id: '' }))
        await agg.flush()

        const rows = getRows()
        expect(rows).toHaveLength(1)
        expect(rows[0].instance_id).toBe('')
        expect(rows[0].count).toBe(2)
    })

    it('produces with key=null', async () => {
        const agg = new AppMetricsAggregator(outputs)
        agg.queue(input())
        await agg.flush()

        const messages = queueMessagesMock.mock.calls[0][0]
        expect(messages[0].key).toBeNull()
    })

    it('clears the buffer after flush', async () => {
        const agg = new AppMetricsAggregator(outputs)
        agg.queue(input())
        await agg.flush()
        queueMessagesMock.mockClear()

        await agg.flush()
        expect(queueMessagesMock).not.toHaveBeenCalled()
    })

    it('writes an explicit timestamp truncated to the hour', async () => {
        const agg = new AppMetricsAggregator(outputs)
        agg.queue(input({ timestamp: DateTime.fromISO('2027-03-04T05:06:07.890Z') }))
        await agg.flush()

        expect(getRows()[0].timestamp).toBe('2027-03-04 05:00:00.000')
    })

    it('sums entries in the same hour and keeps different hours apart', async () => {
        const agg = new AppMetricsAggregator(outputs)
        agg.queue(input({ count: 1, timestamp: DateTime.fromISO('2027-03-04T05:10:00Z') }))
        agg.queue(input({ count: 2, timestamp: DateTime.fromISO('2027-03-04T05:50:00Z') }))
        agg.queue(input({ count: 4, timestamp: DateTime.fromISO('2027-04-03T05:10:00Z') }))
        agg.queue(input({ count: 8 }))
        await agg.flush()

        const countsByTimestamp = Object.fromEntries(getRows().map((r) => [r.timestamp, r.count]))
        expect(Object.keys(countsByTimestamp)).toHaveLength(3)
        expect(countsByTimestamp['2027-03-04 05:00:00.000']).toBe(3)
        expect(countsByTimestamp['2027-04-03 05:00:00.000']).toBe(4)
    })

    describe('minFlushIntervalMs', () => {
        afterEach(() => {
            jest.useRealTimers()
        })

        function startClock(): void {
            jest.useFakeTimers()
            jest.setSystemTime(new Date('2027-03-04T05:00:00Z'))
        }

        it('holds rows across flushes inside the window, then produces one summed row', async () => {
            startClock()
            const agg = new AppMetricsAggregator(outputs, { minFlushIntervalMs: 10_000 })

            agg.queue(input({ count: 1 }))
            await agg.flush()
            agg.queue(input({ count: 2 }))
            await agg.flush()
            expect(queueMessagesMock).not.toHaveBeenCalled()

            jest.setSystemTime(new Date('2027-03-04T05:00:10Z'))
            agg.queue(input({ count: 4 }))
            await agg.flush()

            const rows = getRows()
            expect(rows).toHaveLength(1)
            expect(rows[0].count).toBe(7)
        })

        it('starts a new window after it produces, so the next rows wait again', async () => {
            startClock()
            const agg = new AppMetricsAggregator(outputs, { minFlushIntervalMs: 10_000 })

            jest.setSystemTime(new Date('2027-03-04T05:00:10Z'))
            agg.queue(input())
            await agg.flush()
            expect(queueMessagesMock).toHaveBeenCalledTimes(1)

            jest.setSystemTime(new Date('2027-03-04T05:00:15Z'))
            agg.queue(input())
            await agg.flush()
            expect(queueMessagesMock).toHaveBeenCalledTimes(1)
        })

        it('produces inside the window when forced, so a shutdown loses nothing', async () => {
            startClock()
            const agg = new AppMetricsAggregator(outputs, { minFlushIntervalMs: 10_000 })

            agg.queue(input())
            await agg.flush()
            expect(queueMessagesMock).not.toHaveBeenCalled()

            await agg.flush(true)
            expect(getRows()).toHaveLength(1)
        })

        // A caller only flushes while it has work, so a pod that goes quiet would otherwise hold its
        // last rows until its next batch, which may never come.
        it('produces on its own once the window passes, with no further flush call', async () => {
            startClock()
            const agg = new AppMetricsAggregator(outputs, { minFlushIntervalMs: 10_000 })

            agg.queue(input())
            await agg.flush()
            expect(queueMessagesMock).not.toHaveBeenCalled()

            await jest.advanceTimersByTimeAsync(10_000)

            expect(getRows()).toHaveLength(1)
            await agg.stop()
        })

        // A caller flush just after a tick moves lastFlushAt forward. If the next tick honoured the
        // elapsed check it would skip, and the rows would wait until the tick after that: nearly
        // twice the delay the window promises.
        it('drains on the tick after a caller flush, not the one after that', async () => {
            startClock()
            const agg = new AppMetricsAggregator(outputs, { minFlushIntervalMs: 10_000 })

            jest.setSystemTime(new Date('2027-03-04T05:00:10.100Z'))
            agg.queue(input())
            await agg.flush()
            expect(queueMessagesMock).toHaveBeenCalledTimes(1)

            agg.queue(input({ app_source_id: 'fn-2' }))
            await jest.advanceTimersByTimeAsync(10_000)

            expect(queueMessagesMock).toHaveBeenCalledTimes(2)
            await agg.stop()
        })

        it('runs one produce at a time, so a slow produce cannot hold two batches', async () => {
            startClock()
            let release: () => void = () => {}
            queueMessagesMock.mockImplementation(() => new Promise<void>((resolve) => (release = resolve)))
            const agg = new AppMetricsAggregator(outputs, { minFlushIntervalMs: 10_000 })

            agg.queue(input())
            const first = agg.flush(true)
            expect(queueMessagesMock).toHaveBeenCalledTimes(1)

            agg.queue(input({ app_source_id: 'fn-2' }))
            await jest.advanceTimersByTimeAsync(10_000)
            expect(queueMessagesMock).toHaveBeenCalledTimes(1)

            release()
            await first
        })

        it('produces inside the window once the buffer reaches the row cap', async () => {
            startClock()
            const agg = new AppMetricsAggregator(outputs, { minFlushIntervalMs: 10_000 })

            for (let i = 0; i < MAX_BUFFERED_ROWS; i++) {
                agg.queue(input({ app_source_id: `fn-${i}` }))
            }
            await agg.flush()

            expect(getRows()).toHaveLength(MAX_BUFFERED_ROWS)
        })
    })
})
