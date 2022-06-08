import ClickHouse from '@posthog/clickhouse'
import * as Sentry from '@sentry/node'
import * as fs from 'fs'
import { createPool } from 'generic-pool'
import { StatsD } from 'hot-shots'
import Redis from 'ioredis'
import { Kafka, SASLOptions } from 'kafkajs'
import { DateTime } from 'luxon'
import * as path from 'path'
import { types as pgTypes } from 'pg'
import { ConnectionOptions } from 'tls'

import { getPluginServerCapabilities } from '../../capabilities'
import { defaultConfig } from '../../config/config'
import { KAFKAJS_LOG_LEVEL_MAPPING } from '../../config/constants'
import { JobQueueManager } from '../../main/job-queues/job-queue-manager'
import { connectObjectStorage } from '../../main/services/object_storage'
import { Hub, KafkaSecurityProtocol, PluginServerCapabilities, PluginsServerConfig } from '../../types'
import { ActionManager } from '../../worker/ingestion/action-manager'
import { ActionMatcher } from '../../worker/ingestion/action-matcher'
import { HookCommander } from '../../worker/ingestion/hooks'
import { OrganizationManager } from '../../worker/ingestion/organization-manager'
import { EventsProcessor } from '../../worker/ingestion/process-event'
import { SiteUrlManager } from '../../worker/ingestion/site-url-manager'
import { TeamManager } from '../../worker/ingestion/team-manager'
import { InternalMetrics } from '../internal-metrics'
import { killProcess } from '../kill'
import { status } from '../status'
import { createPostgresPool, createRedis, logOrThrowJobQueueError, UUIDT } from '../utils'
import { PluginsApiKeyManager } from './../../worker/vm/extensions/helpers/api-key-manager'
import { RootAccessManager } from './../../worker/vm/extensions/helpers/root-acess-manager'
import { PromiseManager } from './../../worker/vm/promise-manager'
import { DB } from './db'
import { KafkaProducerWrapper } from './kafka-producer-wrapper'

const { version } = require('../../../package.json')

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

    let statsd: StatsD | undefined

    const conversionBufferEnabledTeams = new Set(
        serverConfig.CONVERSION_BUFFER_ENABLED_TEAMS.split(',').filter(String).map(Number)
    )

    if (serverConfig.STATSD_HOST) {
        status.info('🤔', `Connecting to StatsD...`)
        statsd = new StatsD({
            port: serverConfig.STATSD_PORT,
            host: serverConfig.STATSD_HOST,
            prefix: serverConfig.STATSD_PREFIX,
            telegraf: true,
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

    let kafkaSsl: ConnectionOptions | boolean | undefined
    if (
        serverConfig.KAFKA_CLIENT_CERT_B64 &&
        serverConfig.KAFKA_CLIENT_CERT_KEY_B64 &&
        serverConfig.KAFKA_TRUSTED_CERT_B64
    ) {
        kafkaSsl = {
            cert: Buffer.from(serverConfig.KAFKA_CLIENT_CERT_B64, 'base64'),
            key: Buffer.from(serverConfig.KAFKA_CLIENT_CERT_KEY_B64, 'base64'),
            ca: Buffer.from(serverConfig.KAFKA_TRUSTED_CERT_B64, 'base64'),

            /* Intentionally disabling hostname checking. The Kafka cluster runs in the cloud and Apache
            Kafka on Heroku doesn't currently provide stable hostnames. We're pinned to a specific certificate
            #for this connection even though the certificate doesn't include host information. We rely
            on the ca trust_cert for this purpose. */
            rejectUnauthorized: false,
        }
    } else if (
        serverConfig.KAFKA_SECURITY_PROTOCOL === KafkaSecurityProtocol.Ssl ||
        serverConfig.KAFKA_SECURITY_PROTOCOL === KafkaSecurityProtocol.SaslSsl
    ) {
        kafkaSsl = true
    }

    let kafkaSasl: SASLOptions | undefined
    if (serverConfig.KAFKA_SASL_MECHANISM && serverConfig.KAFKA_SASL_USER && serverConfig.KAFKA_SASL_PASSWORD) {
        kafkaSasl = {
            mechanism: serverConfig.KAFKA_SASL_MECHANISM,
            username: serverConfig.KAFKA_SASL_USER,
            password: serverConfig.KAFKA_SASL_PASSWORD,
        }
    }

    status.info('🤔', `Connecting to ClickHouse...`)
    const clickhouse = new ClickHouse({
        host: serverConfig.CLICKHOUSE_HOST,
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
    await clickhouse.querying('SELECT 1') // test that the connection works
    status.info('👍', `ClickHouse ready`)

    status.info('🤔', `Connecting to Kafka...`)
    const kafka = new Kafka({
        clientId: `plugin-server-v${version}-${instanceId}`,
        brokers: serverConfig.KAFKA_HOSTS.split(','),
        logLevel: KAFKAJS_LOG_LEVEL_MAPPING[serverConfig.KAFKAJS_LOG_LEVEL],
        ssl: kafkaSsl,
        sasl: kafkaSasl,
        connectionTimeout: 7000, // default: 1000
        authenticationTimeout: 7000, // default: 1000
    })
    const producer = kafka.producer({
        retry: { retries: 10, initialRetryTime: 1000, maxRetryTime: 30 },
    })
    await producer.connect()

    const kafkaProducer = new KafkaProducerWrapper(producer, statsd, serverConfig)
    status.info('👍', `Kafka ready`)

    status.info('🤔', `Connecting to Postgresql...`)
    const postgres = createPostgresPool(serverConfig)
    status.info('👍', `Postgresql ready`)

    status.info('🤔', `Connecting to Redis...`)
    const redisPool = createPool<Redis.Redis>(
        {
            create: () => createRedis(serverConfig),
            destroy: async (client) => {
                await client.quit()
            },
        },
        {
            min: serverConfig.REDIS_POOL_MIN_SIZE,
            max: serverConfig.REDIS_POOL_MAX_SIZE,
            autostart: true,
        }
    )
    status.info('👍', `Redis ready`)

    status.info('🤔', `Connecting to object storage...`)
    try {
        connectObjectStorage(serverConfig)
        status.info('👍', 'Object storage ready')
    } catch (e) {
        status.warn('🪣', `Object storage could not be created: ${e}`)
    }

    const db = new DB(
        postgres,
        redisPool,
        kafkaProducer,
        clickhouse,
        statsd,
        serverConfig.PERSON_INFO_CACHE_TTL,
        new Set(serverConfig.PERSON_INFO_TO_REDIS_TEAMS.split(',').filter(String).map(Number))
    )
    const teamManager = new TeamManager(db, serverConfig, statsd)
    const organizationManager = new OrganizationManager(db)
    const pluginsApiKeyManager = new PluginsApiKeyManager(db)
    const rootAccessManager = new RootAccessManager(db)
    const promiseManager = new PromiseManager(serverConfig, statsd)
    const siteUrlManager = new SiteUrlManager(db, serverConfig.SITE_URL)
    const actionManager = new ActionManager(db)
    await actionManager.prepare()

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

        plugins: new Map(),
        pluginConfigs: new Map(),
        pluginConfigsPerTeam: new Map(),
        pluginConfigSecrets: new Map(),
        pluginConfigSecretLookup: new Map(),

        pluginSchedule: null,
        pluginSchedulePromises: { runEveryMinute: {}, runEveryHour: {}, runEveryDay: {} },

        teamManager,
        organizationManager,
        pluginsApiKeyManager,
        rootAccessManager,
        promiseManager,
        siteUrlManager,
        actionManager,
        actionMatcher: new ActionMatcher(db, actionManager, statsd),
        conversionBufferEnabledTeams,
    }

    // :TODO: This is only used on worker threads, not main
    hub.eventsProcessor = new EventsProcessor(hub as Hub)
    hub.jobQueueManager = new JobQueueManager(hub as Hub)
    hub.hookCannon = new HookCommander(db, teamManager, organizationManager, siteUrlManager, statsd)

    if (serverConfig.CAPTURE_INTERNAL_METRICS) {
        hub.internalMetrics = new InternalMetrics(hub as Hub)
    }

    try {
        await hub.jobQueueManager.connectProducer()
    } catch (error) {
        try {
            logOrThrowJobQueueError(hub as Hub, error, `Cannot start job queue producer!`)
        } catch {
            killProcess()
        }
    }

    const closeHub = async () => {
        hub.mmdbUpdateJob?.cancel()
        await hub.jobQueueManager?.disconnectProducer()
        await kafkaProducer.disconnect()
        await redisPool.drain()
        await redisPool.clear()
        await hub.postgres?.end()
    }

    return [hub as Hub, closeHub]
}
