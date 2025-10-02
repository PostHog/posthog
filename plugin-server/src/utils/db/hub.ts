import { Kafka, SASLOptions } from 'kafkajs'
import { DateTime } from 'luxon'
import { hostname } from 'os'
import { types as pgTypes } from 'pg'
import { ConnectionOptions } from 'tls'

import { IntegrationManagerService } from '~/cdp/services/managers/integration-manager.service'
import { InternalCaptureService } from '~/common/services/internal-capture'
import { QuotaLimiting } from '~/common/services/quota-limiting.service'

import { getPluginServerCapabilities } from '../../capabilities'
import { EncryptedFields } from '../../cdp/utils/encryption-utils'
import { buildIntegerMatcher, defaultConfig } from '../../config/config'
import { KAFKAJS_LOG_LEVEL_MAPPING } from '../../config/constants'
import { CookielessManager } from '../../ingestion/cookieless/cookieless-manager'
import { KafkaProducerWrapper } from '../../kafka/producer'
import { Hub, KafkaSecurityProtocol, PluginServerCapabilities, PluginsServerConfig } from '../../types'
import { ActionManager } from '../../worker/ingestion/action-manager'
import { ActionMatcher } from '../../worker/ingestion/action-matcher'
import { AppMetrics } from '../../worker/ingestion/app-metrics'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { ClickhouseGroupRepository } from '../../worker/ingestion/groups/repositories/clickhouse-group-repository'
import { PostgresDualWriteGroupRepository } from '../../worker/ingestion/groups/repositories/postgres-dualwrite-group-repository'
import { PostgresGroupRepository } from '../../worker/ingestion/groups/repositories/postgres-group-repository'
import { PostgresDualWritePersonRepository } from '../../worker/ingestion/persons/repositories/postgres-dualwrite-person-repository'
import { PostgresPersonRepository } from '../../worker/ingestion/persons/repositories/postgres-person-repository'
import { RustyHook } from '../../worker/rusty-hook'
import { ActionManagerCDP } from '../action-manager-cdp'
import { isTestEnv } from '../env-utils'
import { GeoIPService } from '../geoip'
import { logger } from '../logger'
import { getObjectStorage } from '../object_storage'
import { PubSub } from '../pubsub'
import { TeamManager } from '../team-manager'
import { UUIDT } from '../utils'
import { PluginsApiKeyManager } from './../../worker/vm/extensions/helpers/api-key-manager'
import { RootAccessManager } from './../../worker/vm/extensions/helpers/root-acess-manager'
import { Celery } from './celery'
import { DB } from './db'
import { PostgresRouter } from './postgres'
import { createRedisPool } from './redis'

// `node-postgres` would return dates as plain JS Date objects, which would use the local timezone.
// This converts all date fields to a proper luxon UTC DateTime and then casts them to a string
// Unfortunately this must be done on a global object before initializing the `Pool`
pgTypes.setTypeParser(1083 /* types.TypeId.TIME */, (timeStr) =>
    timeStr ? DateTime.fromSQL(timeStr, { zone: 'utc' }).toISO() : null
)
pgTypes.setTypeParser(1114 /* types.TypeId.TIMESTAMP */, (timeStr) =>
    timeStr ? DateTime.fromSQL(timeStr, { zone: 'utc' }).toISO() : null
)
pgTypes.setTypeParser(1184 /* types.TypeId.TIMESTAMPTZ */, (timeStr) =>
    timeStr ? DateTime.fromSQL(timeStr, { zone: 'utc' }).toISO() : null
)

export function createEventsToDropByToken(eventsToDropByTokenStr?: string): Map<string, string[]> {
    const eventsToDropByToken: Map<string, string[]> = new Map()
    if (eventsToDropByTokenStr) {
        eventsToDropByTokenStr.split(',').forEach((pair) => {
            const separatorIndex = pair.indexOf(':')
            const token = pair.substring(0, separatorIndex)
            const distinctID = pair.substring(separatorIndex + 1)
            eventsToDropByToken.set(token, [...(eventsToDropByToken.get(token) || []), distinctID])
        })
    }
    return eventsToDropByToken
}

export async function createHub(
    config: Partial<PluginsServerConfig> = {},
    capabilities: PluginServerCapabilities | null = null
): Promise<Hub> {
    logger.info('ℹ️', `Connecting to all services:`)

    const serverConfig: PluginsServerConfig = {
        ...defaultConfig,
        ...config,
    }
    if (capabilities === null) {
        capabilities = getPluginServerCapabilities(serverConfig)
    }
    const instanceId = new UUIDT()

    logger.info('🤔', `Connecting to Kafka...`)

    const kafka = createKafkaClient(serverConfig)
    const kafkaProducer = await KafkaProducerWrapper.create(serverConfig)
    logger.info('👍', `Kafka ready`)

    const postgres = new PostgresRouter(serverConfig)

    // Instantiate a second router for the Persons database migration
    const postgresPersonMigration = new PostgresRouter({
        ...serverConfig,
        PERSONS_DATABASE_URL: serverConfig.PERSONS_MIGRATION_DATABASE_URL || serverConfig.PERSONS_DATABASE_URL,
        PERSONS_READONLY_DATABASE_URL:
            serverConfig.PERSONS_MIGRATION_READONLY_DATABASE_URL || serverConfig.PERSONS_READONLY_DATABASE_URL,
    })
    // TODO: assert tables are reachable (async calls that cannot be in a constructor)
    logger.info('👍', `Postgres Router ready`)

    logger.info('🤔', `Connecting to ingestion Redis...`)
    const redisPool = createRedisPool(serverConfig, 'ingestion')
    logger.info('👍', `Ingestion Redis ready`)

    logger.info('🤔', `Connecting to cookieless Redis...`)
    const cookielessRedisPool = createRedisPool(serverConfig, 'cookieless')
    logger.info('👍', `Cookieless Redis ready`)

    logger.info('🤔', `Connecting to object storage...`)

    const objectStorage = getObjectStorage(serverConfig)
    if (objectStorage) {
        logger.info('👍', 'Object storage ready')
    } else {
        logger.warn('🪣', `Object storage could not be created`)
    }

    const db = new DB(
        postgres,
        postgresPersonMigration,
        redisPool,
        cookielessRedisPool,
        kafkaProducer,
        serverConfig.PLUGINS_DEFAULT_LOG_LEVEL,
        serverConfig.PERSON_INFO_CACHE_TTL
    )
    const teamManager = new TeamManager(postgres)
    const pluginsApiKeyManager = new PluginsApiKeyManager(db)
    const rootAccessManager = new RootAccessManager(db)
    const pubSub = new PubSub(serverConfig)
    await pubSub.start()
    const rustyHook = new RustyHook(serverConfig)
    const actionManager = new ActionManager(postgres, pubSub)
    const actionManagerCDP = new ActionManagerCDP(postgres)
    const actionMatcher = new ActionMatcher(postgres, actionManager)

    const groupRepository = serverConfig.GROUPS_DUAL_WRITE_ENABLED
        ? new PostgresDualWriteGroupRepository(postgres, postgresPersonMigration, {
              comparisonEnabled: serverConfig.GROUPS_DUAL_WRITE_COMPARISON_ENABLED,
          })
        : new PostgresGroupRepository(postgres)
    const groupTypeManager = new GroupTypeManager(groupRepository, teamManager)

    const personRepositoryOptions = {
        calculatePropertiesSize: serverConfig.PERSON_UPDATE_CALCULATE_PROPERTIES_SIZE,
        comparisonEnabled: serverConfig.PERSONS_DUAL_WRITE_COMPARISON_ENABLED,
    }
    const personRepository = serverConfig.PERSONS_DUAL_WRITE_ENABLED
        ? new PostgresDualWritePersonRepository(postgres, postgresPersonMigration, personRepositoryOptions)
        : new PostgresPersonRepository(postgres, personRepositoryOptions)

    const clickhouseGroupRepository = new ClickhouseGroupRepository(kafkaProducer)
    const cookielessManager = new CookielessManager(serverConfig, cookielessRedisPool, teamManager)
    const geoipService = new GeoIPService(serverConfig)
    await geoipService.get()
    const encryptedFields = new EncryptedFields(serverConfig)
    const integrationManager = new IntegrationManagerService(pubSub, postgres, encryptedFields)
    const quotaLimiting = new QuotaLimiting(serverConfig, teamManager)
    const internalCaptureService = new InternalCaptureService(serverConfig)

    const hub: Hub = {
        ...serverConfig,
        instanceId,
        capabilities,
        db,
        postgres,
        postgresPersonMigration,
        redisPool,
        cookielessRedisPool,
        kafka,
        kafkaProducer,
        objectStorage: objectStorage,
        groupTypeManager,

        plugins: new Map(),
        pluginConfigs: new Map(),
        pluginConfigsPerTeam: new Map(),
        pluginConfigSecrets: new Map(),
        pluginConfigSecretLookup: new Map(),
        pluginSchedule: null,

        teamManager,
        pluginsApiKeyManager,
        rootAccessManager,
        rustyHook,
        actionMatcher,
        groupRepository,
        clickhouseGroupRepository,
        personRepository,
        actionManager,
        actionManagerCDP,
        geoipService,
        pluginConfigsToSkipElementsParsing: buildIntegerMatcher(process.env.SKIP_ELEMENTS_PARSING_PLUGINS, true),
        eventsToDropByToken: createEventsToDropByToken(process.env.DROP_EVENTS_BY_TOKEN_DISTINCT_ID),
        appMetrics: new AppMetrics(
            kafkaProducer,
            serverConfig.APP_METRICS_FLUSH_FREQUENCY_MS,
            serverConfig.APP_METRICS_FLUSH_MAX_QUEUE_SIZE
        ),
        encryptedFields,
        celery: new Celery(serverConfig),
        cookielessManager,
        pubSub,
        integrationManager,
        quotaLimiting,
        internalCaptureService,
    }

    return hub
}

export const closeHub = async (hub: Hub): Promise<void> => {
    logger.info('💤', 'Closing hub...')
    if (!isTestEnv()) {
        await hub.appMetrics?.flush()
    }
    logger.info('💤', 'Closing kafka, redis, postgres...')
    await hub.pubSub.stop()
    await Promise.allSettled([
        hub.kafkaProducer.disconnect(),
        hub.redisPool.drain(),
        hub.postgres?.end(),
        hub.postgresPersonMigration?.end(),
    ])
    await hub.redisPool.clear()
    await hub.cookielessRedisPool.clear()
    logger.info('💤', 'Closing cookieless manager...')
    hub.cookielessManager.shutdown()

    if (isTestEnv()) {
        // Break circular references to allow the hub to be GCed when running unit tests
        // TODO: change these structs to not directly reference the hub
        ;(hub as any).eventsProcessor = undefined
        ;(hub as any).appMetrics = undefined
    }
    logger.info('💤', 'Hub closed!')
}

export function createKafkaClient({
    KAFKA_HOSTS,
    KAFKAJS_LOG_LEVEL,
    KAFKA_SECURITY_PROTOCOL,
    KAFKA_CLIENT_CERT_B64,
    KAFKA_CLIENT_CERT_KEY_B64,
    KAFKA_TRUSTED_CERT_B64,
    KAFKA_SASL_MECHANISM,
    KAFKA_SASL_USER,
    KAFKA_SASL_PASSWORD,
}: PluginsServerConfig) {
    let kafkaSsl: ConnectionOptions | boolean | undefined
    if (KAFKA_CLIENT_CERT_B64 && KAFKA_CLIENT_CERT_KEY_B64 && KAFKA_TRUSTED_CERT_B64) {
        kafkaSsl = {
            cert: Buffer.from(KAFKA_CLIENT_CERT_B64, 'base64'),
            key: Buffer.from(KAFKA_CLIENT_CERT_KEY_B64, 'base64'),
            ca: Buffer.from(KAFKA_TRUSTED_CERT_B64, 'base64'),

            /* Intentionally disabling hostname checking. The Kafka cluster runs in the cloud and Apache
            Kafka on Heroku doesn't currently provide stable hostnames. We're pinned to a specific certificate
            #for this connection even though the certificate doesn't include host information. We rely
            on the ca trust_cert for this purpose. */
            rejectUnauthorized: false,
        }
    } else if (
        KAFKA_SECURITY_PROTOCOL === KafkaSecurityProtocol.Ssl ||
        KAFKA_SECURITY_PROTOCOL === KafkaSecurityProtocol.SaslSsl
    ) {
        kafkaSsl = true
    }

    let kafkaSasl: SASLOptions | undefined
    if (KAFKA_SASL_MECHANISM && KAFKA_SASL_USER && KAFKA_SASL_PASSWORD) {
        kafkaSasl = {
            mechanism: KAFKA_SASL_MECHANISM,
            username: KAFKA_SASL_USER,
            password: KAFKA_SASL_PASSWORD,
        }
    }

    const kafka = new Kafka({
        /* clientId does not need to be unique, and is used in Kafka logs and quota accounting.
           os.hostname() returns the pod name in k8s and the container ID in compose stacks.
           This allows us to quickly find what pod is consuming a given partition */
        clientId: hostname(),
        brokers: KAFKA_HOSTS.split(','),
        logLevel: KAFKAJS_LOG_LEVEL_MAPPING[KAFKAJS_LOG_LEVEL],
        ssl: kafkaSsl,
        sasl: kafkaSasl,
        connectionTimeout: 7000,
        authenticationTimeout: 7000, // default: 1000
    })
    return kafka
}
