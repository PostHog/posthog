import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { HealthCheckResultError, HealthCheckResultOk } from '~/types'

import { CommonIngestionConsumer } from './ingestion-consumer'
import { KafkaConsumerInterface } from './utils/kafka-consumer'

describe('CommonIngestionConsumer', () => {
    const healthyKafka = (): KafkaConsumerInterface =>
        ({ isHealthy: () => new HealthCheckResultOk() }) as unknown as KafkaConsumerInterface

    const outputsWith = (failures: string[]): IngestionOutputs<string> =>
        ({ checkHealth: jest.fn().mockResolvedValue(failures) }) as unknown as IngestionOutputs<string>

    it('skips the producer check when the healthcheck is disabled', async () => {
        const outputs = outputsWith(['events'])
        // Disabled path: a failing producer must not be consulted even though outputs are present.
        const consumer = new CommonIngestionConsumer('analytics', healthyKafka(), outputs, false)

        const result = await consumer.isHealthy()

        expect(result).toBeInstanceOf(HealthCheckResultOk)
        expect(outputs.checkHealth).not.toHaveBeenCalled()
    })

    it('reports unhealthy when an output producer fails its broker check', async () => {
        const consumer = new CommonIngestionConsumer('analytics', healthyKafka(), outputsWith(['events', 'dlq']), true)

        const result = await consumer.isHealthy()

        expect(result).toBeInstanceOf(HealthCheckResultError)
        expect((result as HealthCheckResultError).details).toEqual({ failedProducers: ['events', 'dlq'] })
    })

    it('short-circuits on an unhealthy Kafka consumer before checking producers', async () => {
        const kafka = {
            isHealthy: () => new HealthCheckResultError('kafka down', {}),
        } as unknown as KafkaConsumerInterface
        const outputs = outputsWith([])
        const consumer = new CommonIngestionConsumer('analytics', kafka, outputs, true)

        const result = await consumer.isHealthy()

        expect(result).toBeInstanceOf(HealthCheckResultError)
        expect(outputs.checkHealth).not.toHaveBeenCalled()
    })
})
