import { GroupTypeManager } from '~/common/groups/group-type-manager'
import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { PersonHogConfig } from '~/common/personhog'
import { RoutedRepositories } from '~/common/personhog/personhog-routed-repositories-component'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { EventSchemaEnforcementManager } from '~/common/utils/event-schema-enforcement-manager'
import { TeamManagerComponent } from '~/common/utils/team-manager'
import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { ProducerName } from '~/ingestion/common/outputs/producers'
import { newScope } from '~/ingestion/common/scopes'
import { AiEventSubpipelineFactory } from '~/ingestion/common/subpipelines/ai-subpipeline.contract'
import { IngestionOutputsConfig, getDefaultIngestionConsumerConfig } from '~/ingestion/config'
import { RedisPool } from '~/types'

import { AnalyticsConsumerConfig, AnalyticsOutputs, AnalyticsSharedScope, createAnalyticsConsumer } from './consumer'
import * as pipelineModule from './joined-ingestion-pipeline'

jest.mock('./joined-ingestion-pipeline')

describe('createAnalyticsConsumer', () => {
    function makeConfig(): AnalyticsConsumerConfig {
        return {
            ...getDefaultIngestionConsumerConfig(),
            INGESTION_CONSUMER_CONSUME_TOPIC: 'events_plugin_ingestion',
            CDP_HOG_WATCHER_SAMPLE_RATE: 1,
            ...({} as IngestionOutputsConfig),
            ...({} as PersonHogConfig),
        }
    }

    function makeSharedScope(): AnalyticsSharedScope {
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
                .add('featureFlagCalledDedupRedisPool', {
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
                    start: () => Promise.resolve({ value: {} as AnalyticsOutputs, stop: () => Promise.resolve() }),
                })
                .add('repositories', {
                    start: () => Promise.resolve({ value: {} as RoutedRepositories, stop: () => Promise.resolve() }),
                })
                .add('eventSchemaEnforcementManager', {
                    start: () =>
                        Promise.resolve({
                            value: {} as EventSchemaEnforcementManager,
                            stop: () => Promise.resolve(),
                        }),
                })
                .add('groupTypeManager', {
                    start: () => Promise.resolve({ value: {} as GroupTypeManager, stop: () => Promise.resolve() }),
                })
        )
    }

    beforeEach(() => {
        ;(pipelineModule.createJoinedIngestionPipeline as jest.Mock) = jest.fn().mockReturnValue({
            feed: jest.fn(),
            next: jest.fn(),
        })
    })

    it('defers pipeline construction until scope.start()', () => {
        createAnalyticsConsumer(
            makeConfig(),
            makeSharedScope(),
            jest.fn() as unknown as AiEventSubpipelineFactory,
            'main'
        )

        // The pipeline factory runs inside the extend callback at start time, after the
        // scope's services come up — not at consumer construction time.
        expect(pipelineModule.createJoinedIngestionPipeline).not.toHaveBeenCalled()
    })
})
