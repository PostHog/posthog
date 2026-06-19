import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { ProducerName } from '~/common/outputs'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { PersonHogClient } from '~/common/personhog/client'
import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { newScope } from '~/ingestion/common/scopes'
import { IngestionConsumerConfig, IngestionOutputsConfig } from '~/ingestion/config'
import { RedisPool } from '~/types'
import { PostgresRouter } from '~/utils/db/postgres'
import { TeamManagerComponent } from '~/utils/team-manager'

import { AiConsumerConfig, AiConsumerDeps, AiSharedScope, createAiConsumer } from './consumer'
import * as pipelineModule from './pipeline'

jest.mock('./pipeline')

describe('createAiConsumer', () => {
    function makeConfig(): AiConsumerConfig {
        return {
            INGESTION_CONSUMER_GROUP_ID: 'g',
            INGESTION_CONSUMER_CONSUME_TOPIC: 't',
            INGESTION_PIPELINE: 'ai',
            INGESTION_LANE: 'main',
            KAFKA_BATCH_START_LOGGING_ENABLED: false,
            PLUGIN_SERVER_MODE: null,
            INGESTION_CONSUMER_OVERFLOW_TOPIC: '',
            INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY: false,
            INGESTION_WORKER_CONCURRENT_BATCHES: 1,
            DROP_EVENTS_BY_TOKEN_DISTINCT_ID: '',
            SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID: '',
            INGESTION_FORCE_OVERFLOW_BY_TOKEN_DISTINCT_ID: '',
            ...({} as Pick<
                IngestionConsumerConfig,
                | 'INGESTION_STATEFUL_OVERFLOW_ENABLED'
                | 'INGESTION_STATEFUL_OVERFLOW_REDIS_TTL_SECONDS'
                | 'INGESTION_STATEFUL_OVERFLOW_LOCAL_CACHE_TTL_SECONDS'
                | 'EVENT_OVERFLOW_BUCKET_CAPACITY'
                | 'EVENT_OVERFLOW_BUCKET_REPLENISH_RATE'
                | 'INGESTION_AI_EVENT_SPLITTING_ENABLED'
                | 'INGESTION_AI_EVENT_SPLITTING_TEAMS'
                | 'INGESTION_AI_EVENT_SPLITTING_STRIP_HEAVY_TEAMS'
                | 'INGESTION_AI_EVENT_SPLITTING_PERCENTAGE'
            >),
            ...({} as IngestionOutputsConfig),
        }
    }

    function makeSharedScope(): AiSharedScope {
        // The consumer factory extends this scope but doesn't start it (start happens
        // at the caller), so the shape only has to be type-correct.
        return newScope('shared-test', (b) =>
            b
                .add('postgres', {
                    start: () => Promise.resolve({ value: {} as PostgresRouter, stop: () => Promise.resolve() }),
                })
                .add('redisPool', {
                    start: () => Promise.resolve({ value: {} as RedisPool, stop: () => Promise.resolve() }),
                })
                .add('teamManager', new TeamManagerComponent({} as PostgresRouter))
                .add('cookielessManager', {
                    start: () => Promise.resolve({ value: {} as CookielessManager, stop: () => Promise.resolve() }),
                })
                .add('producerRegistry', {
                    start: () =>
                        Promise.resolve({
                            value: {} as KafkaProducerRegistry<ProducerName>,
                            stop: () => Promise.resolve(),
                        }),
                })
        )
    }

    function makeDeps(overrides: Partial<AiConsumerDeps> = {}): AiConsumerDeps {
        return {
            hogTransformer: {} as HogTransformer,
            personhogClient: {} as PersonHogClient,
            ...overrides,
        }
    }

    beforeEach(() => {
        ;(pipelineModule.createAiIngestionPipeline as jest.Mock) = jest.fn().mockReturnValue({
            feed: jest.fn(),
            next: jest.fn(),
        })
    })

    it('defers pipeline construction until scope.start()', () => {
        createAiConsumer(makeConfig(), makeSharedScope(), makeDeps())

        // The pipeline factory runs inside the extend callback at start time, after the
        // scope's services come up — not at consumer construction time.
        expect(pipelineModule.createAiIngestionPipeline).not.toHaveBeenCalled()
    })

    it('requires a personhog client', () => {
        expect(() => createAiConsumer(makeConfig(), makeSharedScope(), makeDeps({ personhogClient: null }))).toThrow(
            /PersonHog client is required/
        )
    })
})
