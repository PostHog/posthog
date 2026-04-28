import { parseJSON } from '../../../utils/json-parse'
import { IngestionOutputs } from '../../outputs/ingestion-outputs'
import { AppMetricsOutput } from '../outputs'
import { EventFiltersBatchAppMetrics } from './batch-app-metrics'

describe('EventFiltersBatchAppMetrics', () => {
    const mockOutputs = {
        produce: jest.fn().mockResolvedValue(undefined),
        queueMessages: jest.fn().mockResolvedValue(undefined),
    } as unknown as jest.Mocked<Pick<IngestionOutputs<AppMetricsOutput>, 'produce' | 'queueMessages'>> &
        IngestionOutputs<AppMetricsOutput>

    beforeEach(() => {
        jest.clearAllMocks()
    })

    function getQueuedPayloads(): Record<string, unknown>[] {
        const messages = mockOutputs.queueMessages.mock.calls[0][1]
        return messages.map((msg) => parseJSON(msg.value!.toString()) as Record<string, unknown>)
    }

    it('flush is a no-op when nothing was incremented', async () => {
        const metrics = new EventFiltersBatchAppMetrics(mockOutputs)
        await metrics.flush()
        expect(mockOutputs.queueMessages).not.toHaveBeenCalled()
    })

    it('queues one message per unique (teamId, filterId, metricName)', async () => {
        const metrics = new EventFiltersBatchAppMetrics(mockOutputs)

        metrics.increment(1, 'filter-a', 'dropped')
        metrics.increment(2, 'filter-b', 'would_be_dropped')

        await metrics.flush()

        expect(mockOutputs.queueMessages).toHaveBeenCalledTimes(1)
        expect(mockOutputs.queueMessages).toHaveBeenCalledWith('app_metrics', expect.any(Array))

        const payloads = getQueuedPayloads()
        expect(payloads).toHaveLength(2)

        expect(payloads[0]).toMatchObject({
            team_id: 1,
            app_source: 'event_filter',
            app_source_id: 'filter-a',
            metric_kind: 'other',
            metric_name: 'dropped',
            count: 1,
        })

        expect(payloads[1]).toMatchObject({
            team_id: 2,
            app_source: 'event_filter',
            app_source_id: 'filter-b',
            metric_kind: 'other',
            metric_name: 'would_be_dropped',
            count: 1,
        })
    })

    it('aggregates counts for the same key', async () => {
        const metrics = new EventFiltersBatchAppMetrics(mockOutputs)

        metrics.increment(1, 'filter-a', 'dropped')
        metrics.increment(1, 'filter-a', 'dropped')
        metrics.increment(1, 'filter-a', 'dropped')

        await metrics.flush()

        const payloads = getQueuedPayloads()
        expect(payloads).toHaveLength(1)
        expect(payloads[0].count).toBe(3)
    })

    it('separates different metric names for the same team and filter', async () => {
        const metrics = new EventFiltersBatchAppMetrics(mockOutputs)

        metrics.increment(1, 'filter-a', 'dropped')
        metrics.increment(1, 'filter-a', 'would_be_dropped')

        await metrics.flush()

        const payloads = getQueuedPayloads()
        expect(payloads).toHaveLength(2)
    })

    it('separates different teams', async () => {
        const metrics = new EventFiltersBatchAppMetrics(mockOutputs)

        metrics.increment(1, 'filter-a', 'dropped')
        metrics.increment(2, 'filter-b', 'dropped')

        await metrics.flush()

        const payloads = getQueuedPayloads()
        expect(payloads).toHaveLength(2)
    })

    it('sets the Kafka message key to the team id', async () => {
        const metrics = new EventFiltersBatchAppMetrics(mockOutputs)

        metrics.increment(42, 'filter-a', 'dropped')

        await metrics.flush()

        const messages = mockOutputs.queueMessages.mock.calls[0][1]
        expect(messages[0].key!.toString()).toBe('42')
    })

    it('clears counts after flush', async () => {
        const metrics = new EventFiltersBatchAppMetrics(mockOutputs)

        metrics.increment(1, 'filter-a', 'dropped')
        await metrics.flush()

        jest.clearAllMocks()

        await metrics.flush()
        expect(mockOutputs.queueMessages).not.toHaveBeenCalled()
    })
})
