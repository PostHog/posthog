import { TopicPartitionOffset } from 'node-rdkafka'

import { PartitionProgressMonitor, PartitionProgressSource } from './partition-progress-monitor'

describe('PartitionProgressMonitor', () => {
    const topic = 'clickhouse_ai_events_json'
    const start = 1_700_000_000_000

    const committed = (offsets: Record<number, number>): TopicPartitionOffset[] =>
        Object.entries(offsets).map(([partition, offset]) => ({ topic, partition: Number(partition), offset }))

    const createMonitor = (
        consumer: PartitionProgressSource,
        overrides: { stallThresholdMs?: number; stallMinLag?: number } = {}
    ): PartitionProgressMonitor =>
        new PartitionProgressMonitor(consumer, {
            topic,
            groupId: 'evaluation-scheduler-ai-events',
            pollIntervalMs: 30_000,
            stallThresholdMs: 600_000,
            stallMinLag: 1_000,
            ...overrides,
        })

    const createConsumer = (
        highWatermarks: Record<number, number>
    ): PartitionProgressSource & { committedOffsets: jest.Mock } => ({
        committedOffsets: jest.fn(),
        queryWatermarkOffsets: jest.fn((_topic: string, partition: number) =>
            Promise.resolve([0, highWatermarks[partition]] as [number, number])
        ),
    })

    it('reports unhealthy when one partition stops advancing while its neighbours move', async () => {
        const consumer = createConsumer({ 0: 50_000, 1: 50_000 })
        const monitor = createMonitor(consumer)

        consumer.committedOffsets.mockResolvedValue(committed({ 0: 10_000, 1: 10_000 }))
        await monitor.sample(start)
        expect(monitor.health().isError()).toBe(false)

        consumer.committedOffsets.mockResolvedValue(committed({ 0: 20_000, 1: 10_000 }))
        await monitor.sample(start + 600_000)

        const health = monitor.health()
        expect(health.isError()).toBe(true)
        expect(health.toResponse('evaluation-scheduler').details?.stalled).toEqual([
            { partition: 1, lag: 40_000, stalledForMs: 600_000 },
        ])
    })

    it.each([
        ['the partition has no backlog to work through', { 0: 10_100 }, 600_000],
        ['the partition has not been stuck for long enough', { 0: 50_000 }, 599_999],
    ])('stays healthy when %s', async (_case, highWatermarks, elapsedMs) => {
        const consumer = createConsumer(highWatermarks)
        const monitor = createMonitor(consumer)
        consumer.committedOffsets.mockResolvedValue(committed({ 0: 10_000 }))

        await monitor.sample(start)
        await monitor.sample(start + elapsedMs)

        expect(monitor.health().isError()).toBe(false)
    })

    it('restarts the stall clock for a partition reassigned to this consumer', async () => {
        const consumer = createConsumer({ 0: 50_000 })
        const monitor = createMonitor(consumer)

        consumer.committedOffsets.mockResolvedValue(committed({ 0: 10_000 }))
        await monitor.sample(start)

        consumer.committedOffsets.mockResolvedValue([])
        await monitor.sample(start + 300_000)

        consumer.committedOffsets.mockResolvedValue(committed({ 0: 10_000 }))
        await monitor.sample(start + 600_000)

        expect(monitor.health().isError()).toBe(false)
    })

    it('keeps the last verdict when a sample fails', async () => {
        const consumer = createConsumer({ 0: 50_000 })
        const monitor = createMonitor(consumer)

        consumer.committedOffsets.mockResolvedValue(committed({ 0: 10_000 }))
        await monitor.sample(start)
        await monitor.sample(start + 600_000)
        expect(monitor.health().isError()).toBe(true)

        consumer.committedOffsets.mockRejectedValue(new Error('broker unreachable'))
        await monitor.sample(start + 630_000)

        expect(monitor.health().isError()).toBe(true)
    })

    it('exports lag but never fails the health check when the stall threshold is disabled', async () => {
        const consumer = createConsumer({ 0: 50_000 })
        const monitor = createMonitor(consumer, { stallThresholdMs: 0 })
        consumer.committedOffsets.mockResolvedValue(committed({ 0: 10_000 }))

        await monitor.sample(start)
        await monitor.sample(start + 3_600_000)

        expect(monitor.health().isError()).toBe(false)
    })
})
