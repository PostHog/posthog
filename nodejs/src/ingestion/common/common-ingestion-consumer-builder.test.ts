import { IngestionOutputs } from '../outputs/ingestion-outputs'
import { CommonIngestionConsumer, CommonIngestionConsumerConfig } from './common-ingestion-consumer'
import { createCommonIngestionConsumer } from './common-ingestion-consumer-builder'
import { Scope, newScopeBuilder } from './service-registry'

function makeOutputs(failures: string[] = []): IngestionOutputs<string> {
    return {
        checkTopics: jest.fn().mockResolvedValue(failures),
    } as unknown as IngestionOutputs<string>
}

function makeScope(): Scope<{ outputs: IngestionOutputs<string> }> {
    return newScopeBuilder()
        .register('outputs', {
            start: () => Promise.resolve({ value: makeOutputs(), stop: () => Promise.resolve() }),
        })
        .build('consumer')
}

function makeConfig(overrides: Partial<CommonIngestionConsumerConfig> = {}): CommonIngestionConsumerConfig {
    return {
        INGESTION_CONSUMER_GROUP_ID: 'g',
        INGESTION_CONSUMER_CONSUME_TOPIC: 't',
        INGESTION_PIPELINE: 'analytics',
        INGESTION_LANE: 'main',
        KAFKA_BATCH_START_LOGGING_ENABLED: false,
        ...overrides,
    }
}

describe('createCommonIngestionConsumer', () => {
    it('returns a CommonIngestionConsumer wired to the supplied scope and pipeline factory', () => {
        const consumer = createCommonIngestionConsumer({
            config: makeConfig(),
            scope: makeScope(),
            pipeline: () => ({ feed: jest.fn(), next: jest.fn() }),
        })

        expect(consumer).toBeInstanceOf(CommonIngestionConsumer)
    })

    it('defers pipeline construction until start time', () => {
        const factory = jest.fn().mockReturnValue({ feed: jest.fn(), next: jest.fn() })

        createCommonIngestionConsumer({
            config: makeConfig(),
            scope: makeScope(),
            pipeline: factory,
        })

        // Construction alone does not invoke the pipeline factory — the
        // consumer's `start()` does, after the scope has been started.
        expect(factory).not.toHaveBeenCalled()
    })
})
