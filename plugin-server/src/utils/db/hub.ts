import ClickHouse from '@posthog/clickhouse'
import * as Sentry from '@sentry/node'
import * as fs from 'fs'
import { StatsD } from 'hot-shots'
import { Kafka, SASLOptions } from 'kafkajs'
import { DateTime } from 'luxon'
import { hostname } from 'os'
import * as path from 'path'
import { types as pgTypes } from 'pg'
import { ConnectionOptions } from 'tls'

import { getPluginServerCapabilities } from '../../capabilities'
import { buildIntegerMatcher, defaultConfig } from '../../config/config'
import { KAFKAJS_LOG_LEVEL_MAPPING } from '../../config/constants'
import { KAFKA_JOBS } from '../../config/kafka-topics'
import { createRdConnectionConfigFromEnvVars } from '../../kafka/config'
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
import { AppMetrics } from '../../worker/ingestion/app-metrics'
import { OrganizationManager } from '../../worker/ingestion/organization-manager'
import { EventsProcessor } from '../../worker/ingestion/process-event'
import { TeamManager } from '../../worker/ingestion/team-manager'
import { isTestEnv } from '../env-utils'
import { status } from '../status'
import { createRedisPool, UUIDT } from '../utils'
import { PluginsApiKeyManager } from './../../worker/vm/extensions/helpers/api-key-manager'
import { RootAccessManager } from './../../worker/vm/extensions/helpers/root-acess-manager'
import { PromiseManager } from './../../worker/vm/promise-manager'
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
    const producer = await createKafkaProducer({ ...kafkaConnectionConfig, 'linger.ms': 0 })
    return new KafkaProducerWrapper(producer, serverConfig.KAFKA_PRODUCER_WAIT_FOR_ACK)
}

export async function createHub(
    config: Partial<PluginsServerConfig> = {},
    threadId: number | null = null,
    capabilities: PluginServerCapabilities | null = null
): Promise<[Hub, () => Promise<void>]> {
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

    const conversionBufferEnabledTeams = new Set(
        serverConfig.CONVERSION_BUFFER_ENABLED_TEAMS.split(',').filter(String).map(Number)
    )
    const fetchHostnameGuardTeams =
        serverConfig.FETCH_HOSTNAME_GUARD_TEAMS === '*'
            ? null
            : new Set(serverConfig.FETCH_HOSTNAME_GUARD_TEAMS.split(',').filter(String).map(Number))

    const statsd: StatsD | undefined = createStatsdClient(serverConfig, threadId)

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

    const postgres = new PostgresRouter(serverConfig, statsd)
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

    const promiseManager = new PromiseManager(serverConfig, statsd)

    const db = new DB(
        postgres,
        redisPool,
        kafkaProducer,
        clickhouse,
        statsd,
        promiseManager,
        serverConfig.PERSON_INFO_CACHE_TTL
    )
    const teamManager = new TeamManager(postgres, serverConfig, statsd)
    const organizationManager = new OrganizationManager(postgres, teamManager)
    const pluginsApiKeyManager = new PluginsApiKeyManager(db)
    const rootAccessManager = new RootAccessManager(db)

    const enqueuePluginJob = async (job: EnqueuedPluginJob) => {
        // NOTE: we use the producer directly here rather than using the wrapper
        // such that we can a response immediately on error, and thus bubble up
        // any errors in producing. It's important that we ensure that we have
        // an acknowledgement as for instance there are some jobs that are
        // chained, and if we do not manage to produce then the chain will be
        // broken.
        await kafkaProducer.queueMessage({
            topic: KAFKA_JOBS,
            messages: [
                {
                    value: Buffer.from(JSON.stringify(job)),
                    key: Buffer.from(job.pluginConfigTeam.toString()),
                },
            ],
        })
    }

    const hub: Partial<Hub> = {
        ...serverConfig,
        instanceId,
        capabilities,
        db,
        postgres,
        redisPool,
        clickhouse,
        kafka,
        kafkaProducer,
        statsd,
        enqueuePluginJob,
        objectStorage: objectStorage,

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
        promiseManager,
        conversionBufferEnabledTeams,
        fetchHostnameGuardTeams,
        pluginConfigsToSkipElementsParsing: buildIntegerMatcher(process.env.SKIP_ELEMENTS_PARSING_PLUGINS, true),
    }

    // :TODO: This is only used on worker threads, not main
    hub.eventsProcessor = new EventsProcessor(hub as Hub)

    hub.appMetrics = new AppMetrics(
        kafkaProducer,
        serverConfig.APP_METRICS_FLUSH_FREQUENCY_MS,
        serverConfig.APP_METRICS_FLUSH_MAX_QUEUE_SIZE
    )

    const closeHub = async () => {
        if (!isTestEnv()) {
            await hub.appMetrics?.flush()
        }
        await Promise.allSettled([kafkaProducer.disconnect(), redisPool.drain(), hub.postgres?.end()])
        await redisPool.clear()

        // Break circular references to allow the hub to be GCed when running unit tests
        // TODO: change these structs to not directly reference the hub
        hub.eventsProcessor = undefined
        hub.appMetrics = undefined
    }

    return [hub as Hub, closeHub]
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
}

export function createStatsdClient(serverConfig: PluginsServerConfig, threadId: number | null) {
    let statsd: StatsD | undefined

    if (serverConfig.STATSD_HOST) {
        status.info('🤔', `Connecting to StatsD...`)
        statsd = new StatsD({
            port: serverConfig.STATSD_PORT,
            host: serverConfig.STATSD_HOST,
            prefix: serverConfig.STATSD_PREFIX,
            telegraf: true,
            globalTags: serverConfig.PLUGIN_SERVER_MODE
                ? { pluginServerMode: serverConfig.PLUGIN_SERVER_MODE }
                : undefined,
            errorHandler: (error) => {
                status.warn('⚠️', 'StatsD error', error)
                Sentry.captureException(error, {
                    extra: { threadId },
                })
            },
        })
        // don't repeat the same info in each thread
        if (threadId === null) {
            status.info(
                '🪵',
                `Sending metrics to StatsD at ${serverConfig.STATSD_HOST}:${serverConfig.STATSD_PORT}, prefix: "${serverConfig.STATSD_PREFIX}"`
            )
        }
        status.info('👍', `StatsD ready`)
    }
    return statsd
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
