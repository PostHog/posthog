import { USAGE_INGESTION_OUTPUT, UsageIngestionOutput } from '~/common/outputs'
import { IngestionOutput } from '~/common/outputs/ingestion-output'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'

import { createEventUsageBatchFactory } from './index'

describe('createEventUsageBatchFactory', () => {
    const outputs = new IngestionOutputs<UsageIngestionOutput>({
        [USAGE_INGESTION_OUTPUT]: {
            produce: jest.fn(),
            queueMessages: jest.fn(),
            checkHealth: jest.fn(),
            checkTopicExists: jest.fn(),
        } satisfies IngestionOutput,
    })
    const config = {
        USAGE_INGESTION_MODE: 'grpc' as const,
        USAGE_INGESTION_ADDR: 'localhost:7143',
        USAGE_INGESTION_TLS: false,
        USAGE_INGESTION_TIMEOUT_MS: 5_000,
        USAGE_INGESTION_MAX_BATCH_SIZE: 500,
        USAGE_INGESTION_REPORT_TEAMS: '2,4',
    }

    // A batch that accepts nothing reports nothing, and that silence reads the same as a
    // working collector with no traffic. Both halves of the config have to reach the batch,
    // or a deployment looks enabled and bills nobody.
    it.each([
        ['bills a listed team when the address and the team list are both set', config, true],
        ['bills nothing when the address is empty', { ...config, USAGE_INGESTION_ADDR: '' }, false],
        ['bills nothing when the team list is empty', { ...config, USAGE_INGESTION_REPORT_TEAMS: '' }, false],
        ['bills nothing for a team outside the list', { ...config, USAGE_INGESTION_REPORT_TEAMS: '4' }, false],
    ])('%s', (_name, usageConfig, billed) => {
        expect(createEventUsageBatchFactory(usageConfig, 'events')().accepts(2)).toBe(billed)
    })

    it('uses Kafka without a gRPC address when an ingestion output is provided', () => {
        const kafkaConfig = { ...config, USAGE_INGESTION_MODE: 'kafka' as const, USAGE_INGESTION_ADDR: '' }

        expect(createEventUsageBatchFactory(kafkaConfig, 'events', outputs)().accepts(2)).toBe(true)
    })

    it('rejects Kafka mode without the usage ingestion output', () => {
        const kafkaConfig = { ...config, USAGE_INGESTION_MODE: 'kafka' as const }

        expect(() => createEventUsageBatchFactory(kafkaConfig, 'events')).toThrow(
            'USAGE_INGESTION_MODE=kafka requires the usage ingestion Kafka output'
        )
    })

    it('keeps non-event reporters on gRPC when event ingestion uses Kafka', () => {
        const kafkaConfig = { ...config, USAGE_INGESTION_MODE: 'kafka' as const }

        expect(createEventUsageBatchFactory(kafkaConfig, 'exceptions')().accepts(2)).toBe(true)
    })
})
