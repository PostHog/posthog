import ClickHouse from '@posthog/clickhouse'
import * as fs from 'fs'
import { Kafka, SASLOptions } from 'kafkajs'
import { DateTime } from 'luxon'
import { hostname } from 'os'
import * as path from 'path'
import { types as pgTypes } from 'pg'
import { ConnectionOptions } from 'tls'

import { getPluginServerCapabilities } from '../../capabilities'
import { EncryptedFields } from '../../cdp/encryption-utils'
import { buildIntegerMatcher, defaultConfig } from '../../config/config'
import { KAFKAJS_LOG_LEVEL_MAPPING } from '../../config/constants'
import { KAFKA_JOBS } from '../../config/kafka-topics'
import { createRdConnectionConfigFromEnvVars, createRdProducerConfigFromEnvVars } from '../../kafka/config'
import { createKafkaProducer } from '../../kafka/producer'
import { getObjectStorage } from '../../main/services/object_storage'
import {
    EnqueuedPluginJob,
    Hub,
    KafkaSaslMechanism,
    KafkaSecurityProtocol,
    PluginServerCapabilities,
    PluginsServerConfig,
} from '../../types'
import { ActionManager } from '../../worker/ingestion/action-manager'
import { ActionMatcher } from '../../worker/ingestion/action-matcher'
import { AppMetrics } from '../../worker/ingestion/app-metrics'
import { GroupTypeManager } from '../../worker/ingestion/group-type-manager'
import { OrganizationManager } from '../../worker/ingestion/organization-manager'
import { TeamManager } from '../../worker/ingestion/team-manager'
import { RustyHook } from '../../worker/rusty-hook'
import { isTestEnv } from '../env-utils'
import { status } from '../status'
import { createRedisPool, UUIDT } from '../utils'
import { PluginsApiKeyManager } from './../../worker/vm/extensions/helpers/api-key-manager'
import { RootAccessManager } from './../../worker/vm/extensions/helpers/root-acess-manager'
import { Celery } from './celery'
import { DB } from './db'
import { KafkaProducerWrapper } from './kafka-producer-wrapper'
import { PostgresRouter } from './postgres'

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

export async function createKafkaProducerWrapper(serverConfig: PluginsServerConfig): Promise<KafkaProducerWrapper> {
    const kafkaConnectionConfig = createRdConnectionConfigFromEnvVars(serverConfig)
    const producerConfig = createRdProducerConfigFromEnvVars(serverConfig)
    const producer = await createKafkaProducer(kafkaConnectionConfig, producerConfig)
    return new KafkaProducerWrapper(producer)
}

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
    status.info('ℹ️', `Connecting to all services:`)

    const serverConfig: PluginsServerConfig = {
        ...defaultConfig,
        ...config,
    }
    if (capabilities === null) {
        capabilities = getPluginServerCapabilities(serverConfig)
    }
    status.updatePrompt(serverConfig.PLUGIN_SERVER_MODE)
    const instanceId = new UUIDT()

    status.info('🤔', `Connecting to ClickHouse...`)
    const clickhouse = new ClickHouse({
        // We prefer to run queries on the offline cluster.
        host: serverConfig.CLICKHOUSE_OFFLINE_CLUSTER_HOST ?? serverConfig.CLICKHOUSE_HOST,
        port: serverConfig.CLICKHOUSE_SECURE ? 8443 : 8123,
        protocol: serverConfig.CLICKHOUSE_SECURE ? 'https:' : 'http:',
        user: serverConfig.CLICKHOUSE_USER,
        password: serverConfig.CLICKHOUSE_PASSWORD || undefined,
        dataObjects: true,
        queryOptions: {
            database: serverConfig.CLICKHOUSE_DATABASE,
            output_format_json_quote_64bit_integers: false,
        },
        ca: serverConfig.CLICKHOUSE_CA
            ? fs.readFileSync(path.join(serverConfig.BASE_DIR, serverConfig.CLICKHOUSE_CA)).toString()
            : undefined,
        rejectUnauthorized: serverConfig.CLICKHOUSE_CA ? false : undefined,
    })
    status.info('👍', `ClickHouse ready`)

    status.info('🤔', `Connecting to Kafka...`)

    const kafka = createKafkaClient(serverConfig)
    const kafkaProducer = await createKafkaProducerWrapper(serverConfig)
    status.info('👍', `Kafka ready`)

    const postgres = new PostgresRouter(serverConfig)
    // TODO: assert tables are reachable (async calls that cannot be in a constructor)
    status.info('👍', `Postgres Router ready`)

    status.info('🤔', `Connecting to Redis...`)
    const redisPool = createRedisPool(serverConfig)
    status.info('👍', `Redis ready`)

    status.info('🤔', `Connecting to object storage...`)

    const objectStorage = getObjectStorage(serverConfig)
    if (objectStorage) {
        status.info('👍', 'Object storage ready')
    } else {
        status.warn('🪣', `Object storage could not be created`)
    }

    const db = new DB(
        postgres,
        redisPool,
        kafkaProducer,
        clickhouse,
        serverConfig.PLUGINS_DEFAULT_LOG_LEVEL,
        serverConfig.PERSON_INFO_CACHE_TTL
    )
    const teamManager = new TeamManager(postgres, serverConfig)
    const organizationManager = new OrganizationManager(postgres, teamManager)
    const pluginsApiKeyManager = new PluginsApiKeyManager(db)
    const rootAccessManager = new RootAccessManager(db)
    const rustyHook = new RustyHook(serverConfig)

    const actionManager = new ActionManager(postgres, serverConfig)
    const actionMatcher = new ActionMatcher(postgres, actionManager, teamManager)
    const groupTypeManager = new GroupTypeManager(postgres, teamManager)

    const enqueuePluginJob = async (job: EnqueuedPluginJob) => {
        // NOTE: we use the producer directly here rather than using the wrapper
        // such that we can a response immediately on error, and thus bubble up
        // any errors in producing. It's important that we ensure that we have
        // an acknowledgement as for instance there are some jobs that are
        // chained, and if we do not manage to produce then the chain will be
        // broken.
        await kafkaProducer.queueMessage({
            kafkaMessage: {
                topic: KAFKA_JOBS,
                messages: [
                    {
                        value: Buffer.from(JSON.stringify(job)),
                        key: Buffer.from(job.pluginConfigTeam.toString()),
                    },
                ],
            },
            waitForAck: true,
        })
    }

    const hub: Hub = {
        ...serverConfig,
        instanceId,
        capabilities,
        db,
        postgres,
        redisPool,
        clickhouse,
        kafka,
        kafkaProducer,
        enqueuePluginJob,
        objectStorage: objectStorage,
        groupTypeManager,

        plugins: new Map(),
        pluginConfigs: new Map(),
        pluginConfigsPerTeam: new Map(),
        pluginConfigSecrets: new Map(),
        pluginConfigSecretLookup: new Map(),
        pluginSchedule: null,

        teamManager,
        organizationManager,
        pluginsApiKeyManager,
        rootAccessManager,
        rustyHook,
        actionMatcher,
        actionManager,
        pluginConfigsToSkipElementsParsing: buildIntegerMatcher(process.env.SKIP_ELEMENTS_PARSING_PLUGINS, true),
        eventsToDropByToken: createEventsToDropByToken(process.env.DROP_EVENTS_BY_TOKEN_DISTINCT_ID),
        appMetrics: new AppMetrics(
            kafkaProducer,
            serverConfig.APP_METRICS_FLUSH_FREQUENCY_MS,
            serverConfig.APP_METRICS_FLUSH_MAX_QUEUE_SIZE
        ),
        encryptedFields: new EncryptedFields(serverConfig),
        celery: new Celery(serverConfig),
    }

    return hub as Hub
}

export const closeHub = async (hub: Hub): Promise<void> => {
    if (!isTestEnv()) {
        await hub.appMetrics?.flush()
    }
    await Promise.allSettled([hub.kafkaProducer.disconnect(), hub.redisPool.drain(), hub.postgres?.end()])
    await hub.redisPool.clear()

    if (isTestEnv()) {
        // Break circular references to allow the hub to be GCed when running unit tests
        // TODO: change these structs to not directly reference the hub
        ;(hub as any).eventsProcessor = undefined
        ;(hub as any).appMetrics = undefined
    }
}

export type KafkaConfig = {
    KAFKA_HOSTS: string
    KAFKAJS_LOG_LEVEL: keyof typeof KAFKAJS_LOG_LEVEL_MAPPING
    KAFKA_SECURITY_PROTOCOL: 'PLAINTEXT' | 'SSL' | 'SASL_PLAINTEXT' | 'SASL_SSL' | undefined
    KAFKA_CLIENT_CERT_B64?: string
    KAFKA_CLIENT_CERT_KEY_B64?: string
    KAFKA_TRUSTED_CERT_B64?: string
    KAFKA_SASL_MECHANISM?: KafkaSaslMechanism
    KAFKA_SASL_USER?: string
    KAFKA_SASL_PASSWORD?: string
    KAFKA_CLIENT_RACK?: string
    KAFKA_CLIENT_ID?: string
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
}: KafkaConfig) {
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
