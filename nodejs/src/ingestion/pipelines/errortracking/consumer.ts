import { CommonConfig } from '~/common/config'
import { ReadOnlyGroupTypeManager } from '~/common/groups/readonly-group-type-manager'
import { HogTransformer } from '~/common/hog-transformations/hog-transformer.interface'
import { PersonHogConfig } from '~/common/personhog'
import { PersonHogClientComponent } from '~/common/personhog/personhog-client-component'
import { PersonHogGroupReadRepository } from '~/common/personhog/personhog-group-read-repository'
import { PersonHogPersonReadRepository } from '~/common/personhog/personhog-person-read-repository'
import { UsageIngestionConfig, createEventUsageBatchFactory } from '~/common/usage-ingestion'
import { EventIngestionRestrictionManagerComponent } from '~/common/utils/event-ingestion-restrictions'
import { DEFAULT_LOADER_RETRY } from '~/common/utils/lazy-loader'
import { TeamManager } from '~/common/utils/team-manager'
import { CookielessManager } from '~/ingestion/common/cookieless/cookieless-manager'
import { CommonIngestionConsumerConfig, CommonIngestionConsumerScope } from '~/ingestion/common/ingestion-consumer'
import { DisabledOverflowRedirectComponent } from '~/ingestion/common/overflow-redirect/disabled-overflow-redirect'
import { MainLaneOverflowRedirectComponent } from '~/ingestion/common/overflow-redirect/main-lane-overflow-redirect'
import { OverflowLaneOverflowRedirectComponent } from '~/ingestion/common/overflow-redirect/overflow-lane-overflow-redirect'
import { RedisOverflowRepositoryComponent } from '~/ingestion/common/overflow-redirect/overflow-redis-repository'
import { eventRateStrategy } from '~/ingestion/common/overflow-redirect/overflow-strategy'
import { Scope, extend } from '~/ingestion/common/scopes'
import { PromiseSchedulerComponent } from '~/ingestion/common/utils/promise-scheduler'
import { RedisPool } from '~/types'

import { ErrorTrackingConsumerConfig } from './config'
import { CymbalClient } from './cymbal'
import { ErrorTrackingOutputs, createErrorTrackingPipeline } from './error-tracking-pipeline'

export type ErrorTrackingLaneConfig = CommonIngestionConsumerConfig &
    PersonHogConfig &
    UsageIngestionConfig &
    Pick<
        ErrorTrackingConsumerConfig,
        | 'ERROR_TRACKING_CYMBAL_BASE_URL'
        | 'ERROR_TRACKING_CYMBAL_TIMEOUT_MS'
        | 'ERROR_TRACKING_CYMBAL_MAX_BODY_BYTES'
        | 'ERROR_TRACKING_OVERFLOW_BUCKET_CAPACITY'
        | 'ERROR_TRACKING_OVERFLOW_BUCKET_REPLENISH_RATE'
        | 'ERROR_TRACKING_STATEFUL_OVERFLOW_REDIS_TTL_SECONDS'
        | 'ERROR_TRACKING_STATEFUL_OVERFLOW_LOCAL_CACHE_TTL_SECONDS'
        | 'ERROR_TRACKING_OVERFLOW_PRESERVE_PARTITION_LOCALITY'
        | 'INGESTION_OVERFLOW_MODE'
    > &
    Pick<CommonConfig, 'PLUGIN_SERVER_MODE'>

/**
 * Services shared from the server scope. The server builds the hog transformer
 * (cdp-owned, so the lane can't construct it) and the outputs, because the same
 * outputs instance backs the transformer's monitoring. The personhog client is
 * owned by the error tracking scope, not shared in here.
 */
export type ErrorTrackingSharedScope = Scope<{
    redisPool: RedisPool
    teamManager: TeamManager
    cookielessManager: CookielessManager
    hogTransformer: HogTransformer
    outputs: ErrorTrackingOutputs
}>

export function createErrorTrackingConsumer(config: ErrorTrackingLaneConfig, sharedScope: ErrorTrackingSharedScope) {
    const overflowMode = config.INGESTION_OVERFLOW_MODE
    const preservePartitionLocality = config.ERROR_TRACKING_OVERFLOW_PRESERVE_PARTITION_LOCALITY
    const clientLabel = config.PLUGIN_SERVER_MODE ?? 'unknown'

    const overflowScope = extend(sharedScope, 'errortracking-overflow', (container, builder) =>
        builder.add(
            'overflowRedisRepository',
            new RedisOverflowRepositoryComponent(
                container.redisPool,
                config.ERROR_TRACKING_STATEFUL_OVERFLOW_REDIS_TTL_SECONDS
            )
        )
    )

    const scope = extend(overflowScope, 'errortracking', (container, builder) =>
        builder
            .add('promiseScheduler', new PromiseSchedulerComponent())
            .add(
                'eventIngestionRestrictionManager',
                new EventIngestionRestrictionManagerComponent(container.redisPool, { pipeline: 'errortracking' })
            )
            .add(
                'overflowRedirectService',
                overflowMode === 'redirect'
                    ? new MainLaneOverflowRedirectComponent({
                          redisRepository: container.overflowRedisRepository,
                          localCacheTTLSeconds: config.ERROR_TRACKING_STATEFUL_OVERFLOW_LOCAL_CACHE_TTL_SECONDS,
                          strategies: [
                              {
                                  ...eventRateStrategy(),
                                  bucketCapacity: config.ERROR_TRACKING_OVERFLOW_BUCKET_CAPACITY,
                                  replenishRate: config.ERROR_TRACKING_OVERFLOW_BUCKET_REPLENISH_RATE,
                              },
                          ],
                          overflowType: 'errortracking',
                      })
                    : new DisabledOverflowRedirectComponent()
            )
            .add(
                'overflowLaneTTLRefreshService',
                overflowMode === 'consume'
                    ? new OverflowLaneOverflowRedirectComponent({
                          redisRepository: container.overflowRedisRepository,
                          overflowType: 'errortracking',
                      })
                    : new DisabledOverflowRedirectComponent()
            )
            .add('personhogClient', new PersonHogClientComponent(config))
    )

    const cymbalClient = new CymbalClient({
        baseUrl: config.ERROR_TRACKING_CYMBAL_BASE_URL,
        timeoutMs: config.ERROR_TRACKING_CYMBAL_TIMEOUT_MS,
        maxBodyBytes: config.ERROR_TRACKING_CYMBAL_MAX_BODY_BYTES,
    })
    const createEventUsageBatch = createEventUsageBatchFactory(config, 'exceptions')

    return new CommonIngestionConsumerScope('errortracking', config, scope, ({ container }) =>
        createErrorTrackingPipeline({
            outputs: container.outputs,
            promiseScheduler: container.promiseScheduler,
            teamManager: container.teamManager,
            // Read-only person/group access — read through personhog, never written.
            personRepository: new PersonHogPersonReadRepository(container.personhogClient, clientLabel),
            hogTransformer: container.hogTransformer,
            cymbalClient,
            groupTypeManager: new ReadOnlyGroupTypeManager(
                new PersonHogGroupReadRepository(container.personhogClient, clientLabel),
                { loaderRetry: DEFAULT_LOADER_RETRY }
            ),
            cookielessManager: container.cookielessManager,
            eventIngestionRestrictionManager: container.eventIngestionRestrictionManager,
            overflowMode,
            preservePartitionLocality,
            overflowRedirectService: container.overflowRedirectService,
            overflowLaneTTLRefreshService: container.overflowLaneTTLRefreshService,
            topHog: container.topHog,
            createEventUsageBatch,
        })
    )
}
