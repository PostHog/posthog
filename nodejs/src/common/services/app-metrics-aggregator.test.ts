import { IngestionOutput } from '../../ingestion/outputs/ingestion-output'
import { parseJSON } from '../../utils/json-parse'
import { AppMetricInput, AppMetricsAggregator } from './app-metrics-aggregator'

function makeOutput(): IngestionOutput & { queueMessagesMock: jest.Mock<Promise<void>, [any[]]> } {
    const queueMessagesMock = jest.fn().mockResolvedValue(undefined)
    return {
        produce: jest.fn().mockResolvedValue(undefined),
        queueMessages: queueMessagesMock,
        checkHealth: jest.fn().mockResolvedValue(undefined),
        checkTopicExists: jest.fn().mockResolvedValue(undefined),
        queueMessagesMock,
    } as unknown as IngestionOutput & { queueMessagesMock: jest.Mock<Promise<void>, [any[]]> }
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
    let output: ReturnType<typeof makeOutput>

    beforeEach(() => {
        output = makeOutput()
    })

    function getRows(callIndex = 0): Record<string, unknown>[] {
        const messages = output.queueMessagesMock.mock.calls[callIndex][0]
        return messages.map((m: { value: Buffer }) => parseJSON(m.value.toString()) as Record<string, unknown>)
    }

    it('flush is a no-op when nothing was queued', async () => {
        const agg = new AppMetricsAggregator(output)
        await agg.flush()
        expect(output.queueMessagesMock).not.toHaveBeenCalled()
    })

    it('serializes the v2 schema with all six identity fields, count, and a timestamp', async () => {
        const agg = new AppMetricsAggregator(output)
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
        const agg = new AppMetricsAggregator(output)
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
        const agg = new AppMetricsAggregator(output)
        agg.queue(input())
        agg.queue(input(override as Partial<AppMetricInput>))
        await agg.flush()

        expect(getRows()).toHaveLength(2)
    })

    it('treats undefined instance_id as ""', async () => {
        const agg = new AppMetricsAggregator(output)
        agg.queue(input({ instance_id: undefined }))
        agg.queue(input({ instance_id: '' }))
        await agg.flush()

        const rows = getRows()
        expect(rows).toHaveLength(1)
        expect(rows[0].instance_id).toBe('')
        expect(rows[0].count).toBe(2)
    })

    it('produces with key=null', async () => {
        const agg = new AppMetricsAggregator(output)
        agg.queue(input())
        await agg.flush()

        const messages = output.queueMessagesMock.mock.calls[0][0]
        expect(messages[0].key).toBeNull()
    })

    it('clears the buffer after flush', async () => {
        const agg = new AppMetricsAggregator(output)
        agg.queue(input())
        await agg.flush()
        output.queueMessagesMock.mockClear()

        await agg.flush()
        expect(output.queueMessagesMock).not.toHaveBeenCalled()
    })
})
