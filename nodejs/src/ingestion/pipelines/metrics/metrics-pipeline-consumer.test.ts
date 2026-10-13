import { Message } from 'node-rdkafka'

import { KafkaConsumerV2 } from '~/common/kafka/consumer/consumer-v2'
import { DependencyUnavailableError, MessageSizeTooLarge } from '~/common/utils/db/error'
import { createMockIngestionOutputs } from '~/tests/helpers/mock-ingestion-outputs'
import { createTestTeam } from '~/tests/helpers/team'

import { getDefaultMetricsIngestionConsumerConfig } from './config'
import { MetricsPipelineConsumer, MetricsPipelineConsumerDeps } from './metrics-pipeline-consumer'

jest.mock('~/common/utils/logger', () => ({
    logger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}))
jest.mock('~/common/kafka/consumer/consumer-v2', () => ({
    KafkaConsumerV2: jest.fn().mockImplementation(() => ({
        connect: jest.fn().mockResolvedValue(undefined),
        disconnect: jest.fn().mockResolvedValue(undefined),
        isHealthy: jest.fn().mockReturnValue({ status: 'ok' }),
    })),
}))
jest.mock('./services/metrics-redis', () => ({ createMetricsRateLimiterRedis: jest.fn(() => ({})) }))
jest.mock('./services/metrics-rate-limiter.service', () => ({
    MetricsRateLimiterService: jest.fn().mockImplementation(() => ({
        filterMessages: (messages: unknown[]) => Promise.resolve({ allowed: messages, dropped: [] }),
    })),
}))

describe('MetricsPipelineConsumer', () => {
    const team = createTestTeam({ id: 1, api_token: 'token-a' })
    let outputs: ReturnType<typeof createMockIngestionOutputs>
    let teamManager: { getTeam: jest.Mock; getTeamByToken: jest.Mock }
    let consumer: MetricsPipelineConsumer

    const message: Message = {
        value: Buffer.from('opaque avro packet'),
        key: null,
        headers: [{ token: Buffer.from(team.api_token) }, { record_count: Buffer.from('1') }],
        topic: 'metrics_ingestion',
        partition: 0,
        offset: 0,
        size: 0,
    }

    beforeEach(() => {
        outputs = createMockIngestionOutputs()
        teamManager = { getTeam: jest.fn(), getTeamByToken: jest.fn().mockResolvedValue(team) }
        consumer = new MetricsPipelineConsumer(getDefaultMetricsIngestionConsumerConfig(), {
            teamManager,
            quotaLimiting: { isTeamTokenQuotaLimited: jest.fn().mockResolvedValue(false) },
            outputs,
        } as unknown as MetricsPipelineConsumerDeps)
    })

    it('returns the batch before the produce is acked and settles the background task after it', async () => {
        let ack: () => void = () => {}
        outputs.produce.mockReturnValueOnce(new Promise<void>((resolve) => (ack = resolve)))

        const { backgroundTask } = await consumer.handleKafkaBatch([message])

        let settled = false
        void backgroundTask!.then(() => (settled = true))
        await new Promise((resolve) => setImmediate(resolve))
        expect(settled).toBe(false)

        expect(outputs.queueMessages).not.toHaveBeenCalled()

        ack()
        await backgroundTask
        expect(outputs.produce).toHaveBeenCalledTimes(1)
        expect(outputs.queueMessages).toHaveBeenCalled()
    })

    it('runs on consumer-v2, which stores no offsets when the background task rejects', () => {
        const config = getDefaultMetricsIngestionConsumerConfig()
        expect(KafkaConsumerV2).toHaveBeenCalledWith({
            groupId: config.METRICS_INGESTION_CONSUMER_GROUP_ID,
            topic: config.METRICS_INGESTION_CONSUMER_CONSUME_TOPIC,
        })
    })

    it('rejects the background task when the produce and the DLQ write both fail', async () => {
        const error = new MessageSizeTooLarge('too large', new Error('too large'))
        outputs.produce.mockRejectedValue(error)

        const { backgroundTask } = await consumer.handleKafkaBatch([message])

        await expect(backgroundTask).rejects.toBe(error)
        expect(outputs.produce).toHaveBeenCalledTimes(2)
        expect(outputs.queueMessages).not.toHaveBeenCalled()
    })

    it('rejects the background task when a permanent team lookup error and its DLQ write both fail', async () => {
        teamManager.getTeamByToken.mockRejectedValue(new Error('bad token row'))
        const dlqError = new Error('broker down')
        outputs.produce.mockRejectedValue(dlqError)

        const { backgroundTask } = await consumer.handleKafkaBatch([message])

        await expect(backgroundTask).rejects.toBe(dlqError)
        expect(outputs.produce).toHaveBeenCalledTimes(1)
        expect(outputs.queueMessages).not.toHaveBeenCalled()
    })

    it('fails the batch when the team lookup keeps failing with a retriable error', async () => {
        const error = new DependencyUnavailableError('pg down', 'Postgres', new Error('pg down'))
        teamManager.getTeamByToken.mockRejectedValue(error)

        await expect(consumer.handleKafkaBatch([message])).rejects.toBe(error)
        expect(teamManager.getTeamByToken).toHaveBeenCalledTimes(3)
        expect(outputs.produce).not.toHaveBeenCalled()
    })
})
