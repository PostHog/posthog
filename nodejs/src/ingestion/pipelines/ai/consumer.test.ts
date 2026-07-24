import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { PersonHogConfig } from '~/common/personhog'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { TeamManagerComponent } from '~/common/utils/team-manager'
import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { ProducerName } from '~/ingestion/common/outputs/producers'
import { newScope } from '~/ingestion/common/scopes'
import { IngestionConsumerConfig, IngestionOutputsConfig } from '~/ingestion/config'
import { RedisPool } from '~/types'

import { AiConsumerConfig, AiOutputs, AiSharedScope, createAiConsumer } from './consumer'
import * as pipelineModule from './pipeline'

jest.mock('./pipeline')

describe('createAiConsumer', () => {
    function makeConfig(): AiConsumerConfig {
        return {
            INGESTION_CONSUMER_GROUP_ID: 'g',
            INGESTION_CONSUMER_CONSUME_TOPIC: 't',
            INGESTION_PIPELINE: 'ai',
            INGESTION_LANE: 'main',
            INGESTION_OVERFLOW_MODE: 'disabled',
            KAFKA_BATCH_START_LOGGING_ENABLED: false,
            INGESTION_CONSUMER_OVERFLOW_TOPIC: '',
            INGESTION_OVERFLOW_PRESERVE_PARTITION_LOCALITY: false,
            INGESTION_WORKER_CONCURRENT_BATCHES: 1,
            INGESTION_GATHER_MAX_WAIT_MS: 50,
            INGESTION_GATHER_MIN_ITEMS: 1000,
            DROP_EVENTS_BY_TOKEN_DISTINCT_ID: '',
            SKIP_PERSONS_PROCESSING_BY_TOKEN_DISTINCT_ID: '',
            INGESTION_FORCE_OVERFLOW_BY_TOKEN_DISTINCT_ID: '',
            EVENT_SCHEMA_ENFORCEMENT_ENABLED: false,
            CDP_HOG_WATCHER_SAMPLE_RATE: 1,
            // Read eagerly by createAiConsumer (not deferred like the scope-builder services
            // below), so these need real fail-closed values rather than the cast-away pattern.
            AI_BLOB_S3_BUCKET: '',
            AI_BLOB_S3_PREFIX: '',
            AI_BLOB_S3_ENDPOINT: '',
            AI_BLOB_S3_REGION: 'us-east-1',
            AI_BLOB_S3_ACCESS_KEY_ID: '',
            AI_BLOB_S3_SECRET_ACCESS_KEY: '',
            AI_BLOB_S3_TIMEOUT_MS: 30000,
            AI_BLOB_OFFLOAD_TEAMS: '',
            AI_BLOB_OFFLOAD_MIN_BASE64_LENGTH: 8192,
            AI_BLOB_OFFLOAD_MAX_BLOBS_PER_EVENT: 50,
            AI_BLOB_OFFLOAD_UPLOAD_MAX_CONCURRENCY: 8,
            AI_BLOB_OFFLOAD_TOUCH_AFTER_HOURS: 20,
            ...({} as Pick<
                IngestionConsumerConfig,
                | 'INGESTION_STATEFUL_OVERFLOW_REDIS_TTL_SECONDS'
                | 'INGESTION_STATEFUL_OVERFLOW_LOCAL_CACHE_TTL_SECONDS'
                | 'EVENT_OVERFLOW_BUCKET_CAPACITY'
                | 'EVENT_OVERFLOW_BUCKET_REPLENISH_RATE'
            >),
            ...({} as IngestionOutputsConfig),
            ...({} as PersonHogConfig),
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
                .add('hogTransformer', {
                    start: () => Promise.resolve({ value: {} as HogTransformer, stop: () => Promise.resolve() }),
                })
                .add('outputs', {
                    start: () => Promise.resolve({ value: {} as AiOutputs, stop: () => Promise.resolve() }),
                })
        )
    }

    beforeEach(() => {
        ;(pipelineModule.createAiIngestionPipeline as jest.Mock) = jest.fn().mockReturnValue({
            feed: jest.fn(),
            next: jest.fn(),
        })
    })

    it('defers pipeline construction until scope.start()', () => {
        createAiConsumer(makeConfig(), makeSharedScope())

        // The pipeline factory runs inside the extend callback at start time, after the
        // scope's services come up — not at consumer construction time.
        expect(pipelineModule.createAiIngestionPipeline).not.toHaveBeenCalled()
    })
})
