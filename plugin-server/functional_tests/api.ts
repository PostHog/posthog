import ClickHouse from '@posthog/clickhouse'
import { makeWorkerUtils, WorkerUtils } from 'graphile-worker'
import Redis from 'ioredis'
import parsePrometheusTextFormat from 'parse-prometheus-text-format'
import { PoolClient } from 'pg'

import { defaultConfig } from '../src/config/config'
import { KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS } from '../src/config/kafka-topics'
import {
    ActionStep,
    Hook,
    Plugin,
    PluginConfig,
    PluginLogEntry,
    RawAction,
    RawClickHouseEvent,
    RawSessionReplayEvent,
} from '../src/types'
import { PostgresRouter, PostgresUse } from '../src/utils/db/postgres'
import { parseRawClickHouseEvent } from '../src/utils/event'
import { createPostgresPool, UUIDT } from '../src/utils/utils'
import { insertRow } from '../tests/helpers/sql'
import { waitForExpect } from './expectations'
import { produce } from './kafka'

let clickHouseClient: ClickHouse
export let postgres: PostgresRouter
let redis: Redis.Redis
let graphileWorker: WorkerUtils

beforeAll(async () => {
    // Setup connections to kafka, clickhouse, and postgres
    postgres = new PostgresRouter({ ...defaultConfig, POSTGRES_CONNECTION_POOL_SIZE: 1 }, null)
    graphileWorker = await makeWorkerUtils({
        pgPool: createPostgresPool(defaultConfig.DATABASE_URL!, 1),
    })
    clickHouseClient = new ClickHouse({
        host: defaultConfig.CLICKHOUSE_HOST,
        port: 8123,
        dataObjects: true,
        queryOptions: {
            database: defaultConfig.CLICKHOUSE_DATABASE,
            output_format_json_quote_64bit_integers: false,
        },
    })
    redis = new Redis(defaultConfig.REDIS_URL)
})

afterAll(async () => {
    await Promise.all([postgres.end(), redis.disconnect()])
})

export const capture = async ({
    teamId,
    distinctId,
    uuid,
    event,
    properties = {},
    token = null,
    sentAt = new Date(),
    eventTime = new Date(),
    now = new Date(),
    $set = undefined,
    $set_once = undefined,
    topic = ['$performance_event', '$snapshot_items'].includes(event)
        ? KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS
        : 'events_plugin_ingestion',
}: {
    teamId: number | null
    distinctId: string
    uuid: string
    event: string
    properties?: object
    token?: string | null
    sentAt?: Date
    eventTime?: Date
    now?: Date
    topic?: string
    $set?: object
    $set_once?: object
}) => {
    // WARNING: this capture method is meant to simulate the ingestion of events
    // from the capture endpoint, but there is no guarantee that it is 100%
    // accurate.
    return await produce({
        topic,
        message: Buffer.from(
            JSON.stringify({
                token,
                distinct_id: distinctId,
                ip: '',
                site_url: '',
                team_id: teamId,
                now: now,
                sent_at: sentAt,
                uuid: uuid,
                data: JSON.stringify({
                    event,
                    properties: { ...properties, uuid },
                    team_id: teamId,
                    timestamp: eventTime,
                    $set,
                    $set_once,
                }),
            })
        ),
        key: teamId ? teamId.toString() : '',
    })
}

export const createPluginAttachment = async ({
    teamId,
    pluginConfigId,
    fileSize,
    contentType,
    fileName,
    key,
    contents,
}: {
    teamId: number
    pluginConfigId: number
    fileSize: number
    contentType: string
    fileName: string
    key: string
    contents: string
    client?: PoolClient
}) => {
    return await insertRow(postgres, 'posthog_pluginattachment', {
        team_id: teamId,
        plugin_config_id: pluginConfigId,
        key: key,
        content_type: contentType,
        file_name: fileName,
        file_size: fileSize,
        contents: contents,
    })
}

export const createPlugin = async (plugin: Omit<Plugin, 'id'>) => {
    return await insertRow(postgres, 'posthog_plugin', {
        ...plugin,
        config_schema: {},
        from_json: false,
        from_web: false,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        is_preinstalled: false,
        capabilities: {},
    })
}

export const createPluginConfig = async (
    pluginConfig: Omit<PluginConfig, 'id' | 'created_at' | 'enabled' | 'order' | 'has_error'>
) => {
    return await insertRow(postgres, 'posthog_pluginconfig', {
        ...pluginConfig,
        config: pluginConfig.config ?? {},
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        enabled: true,
        order: 0,
    })
}

export const getPluginConfig = async (teamId: number, pluginId: number) => {
    const queryResult = (await postgres.query(
        PostgresUse.COMMON_WRITE,
        `SELECT *
         FROM posthog_pluginconfig
         WHERE team_id = $1
           AND id = $2`,
        [teamId, pluginId],
        'getPluginConfig'
    )) as { rows: any[] }
    return queryResult.rows[0]
}

export const updatePluginConfig = async (
    teamId: number,
    pluginConfigId: string,
    pluginConfig: Partial<PluginConfig>
) => {
    await postgres.query(
        PostgresUse.COMMON_WRITE,
        `UPDATE posthog_pluginconfig SET config = $1, updated_at = $2 WHERE id = $3 AND team_id = $4`,
        [pluginConfig.config ?? {}, pluginConfig.updated_at, pluginConfigId, teamId],
        'updatePluginConfig'
    )
}

export const reloadPlugins = async () => await redis.publish('reload-plugins', '')

export const waitForPluginToLoad = (pluginConfig: any) => {
    return waitForExpect(async () => {
        const logEntries = await fetchPluginLogEntries(pluginConfig.id)
        const setUp = logEntries.filter(({ message }) => message.includes('Plugin loaded'))
        expect(setUp.length).toBeGreaterThan(0)
    })
}

export const createAndReloadPluginConfig = async (teamId: number, pluginId: number) => {
    const pluginConfig = await createPluginConfig({ team_id: teamId, plugin_id: pluginId, config: {} })
    await reloadPlugins()
    // We wait for some log entries for the plugin, to make sure it's ready to
    // process events.
    await waitForPluginToLoad(pluginConfig)
    return pluginConfig
}

export const disablePluginConfig = async (teamId: number, pluginConfigId: number) => {
    await postgres.query(
        PostgresUse.COMMON_WRITE,
        `UPDATE posthog_pluginconfig
         SET enabled = false
         WHERE id = $1
           AND team_id = $2`,
        [pluginConfigId, teamId],
        'disablePluginConfig'
    )
}

export const enablePluginConfig = async (teamId: number, pluginConfigId: number) => {
    await postgres.query(
        PostgresUse.COMMON_WRITE,
        `UPDATE posthog_pluginconfig
         SET enabled = true
         WHERE id = $1
           AND team_id = $2`,
        [pluginConfigId, teamId],
        'enablePluginConfig'
    )
}

export const schedulePluginJob = async ({
    teamId,
    pluginConfigId,
    type,
    taskType,
    payload,
}: {
    teamId: number
    pluginConfigId: number
    type: string
    taskType: string
    payload: any
}) => {
    return await graphileWorker.addJob(taskType, { teamId, pluginConfigId, type, payload })
}

export const getScheduledPluginJob = async (jobId: string) => {
    const result = await postgres.query(
        PostgresUse.COMMON_WRITE,
        `SELECT *
         FROM graphile_worker.jobs
         WHERE id = $1`,
        [jobId],
        'getScheduledPluginJob'
    )
    return result.rows[0]
}

export const reloadAction = async (teamId: number, actionId: number) => {
    await redis.publish('reload-action', JSON.stringify({ teamId, actionId }))
}

export const fetchEvents = async (teamId: number, uuid?: string) => {
    const queryResult = (await clickHouseClient.querying(`
        SELECT *,
               if(notEmpty(overrides.person_id), overrides.person_id, e.person_id) as person_id
        FROM events e
                 LEFT OUTER JOIN
             (SELECT argMax(override_person_id, version) as person_id,
                     old_person_id
              FROM person_overrides
              WHERE team_id = ${teamId}
              GROUP BY old_person_id) AS overrides ON e.person_id = overrides.old_person_id
        WHERE team_id = ${teamId} ${uuid ? `AND uuid = '${uuid}'` : ``}
        ORDER BY timestamp ASC
    `)) as unknown as ClickHouse.ObjectQueryResult<RawClickHouseEvent>
    return queryResult.data.map(parseRawClickHouseEvent)
}

export const fetchPersons = async (teamId: number) => {
    const queryResult = (await clickHouseClient.querying(
        `SELECT * FROM person WHERE team_id = ${teamId} ORDER BY created_at ASC`
    )) as unknown as ClickHouse.ObjectQueryResult<any>
    return queryResult.data.map((person) => ({ ...person, properties: JSON.parse(person.properties) }))
}

export const fetchPostgresPersons = async (teamId: number) => {
    const { rows } = await postgres.query(
        PostgresUse.COMMON_WRITE,
        `SELECT *
         FROM posthog_person
         WHERE team_id = $1`,
        [teamId],
        'fetchPostgresPersons'
    )
    return rows
}

export const fetchSessionReplayEvents = async (teamId: number, sessionId?: string) => {
    const queryResult = (await clickHouseClient.querying(
        `SELECT min(min_first_timestamp) as min_fs_ts, any(team_id), any(distinct_id), session_id FROM session_replay_events WHERE team_id = ${teamId} ${
            sessionId ? ` AND session_id = '${sessionId}'` : ''
        } group by session_id ORDER BY min_fs_ts ASC`
    )) as unknown as ClickHouse.ObjectQueryResult<RawSessionReplayEvent>
    return queryResult.data.map((event) => {
        return {
            ...event,
        }
    })
}

export const fetchPluginConsoleLogEntries = async (pluginConfigId: number) => {
    const { data: logEntries } = (await clickHouseClient.querying(`
        SELECT * FROM plugin_log_entries
        WHERE plugin_config_id = ${pluginConfigId} AND source = 'CONSOLE'
    `)) as unknown as ClickHouse.ObjectQueryResult<PluginLogEntry>
    return logEntries.map((entry) => ({ ...entry, message: JSON.parse(entry.message) }))
}

export const fetchPluginLogEntries = async (pluginConfigId: number) => {
    const { data: logEntries } = (await clickHouseClient.querying(`
        SELECT * FROM plugin_log_entries
        WHERE plugin_config_id = ${pluginConfigId}
    `)) as unknown as ClickHouse.ObjectQueryResult<PluginLogEntry>
    return logEntries
}

export const createOrganization = async (organizationProperties = {}) => {
    const organizationId = new UUIDT().toString()
    await insertRow(postgres, 'posthog_organization', {
        id: organizationId,
        name: 'TEST ORG',
        plugins_access_level: 9,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        personalization: '{}', // DEPRECATED
        setup_section_2_completed: true, // DEPRECATED
        for_internal_metrics: false,
        available_features: [],
        domain_whitelist: [],
        is_member_join_email_enabled: false,
        slug: Math.round(Math.random() * 20000),
        ...organizationProperties,
    })
    return organizationId
}

export const createTeam = async (
    organizationId: string,
    slack_incoming_webhook?: string,
    token?: string,
    sessionRecordingOptIn = true
) => {
    const team = await insertRow(postgres, 'posthog_team', {
        organization_id: organizationId,
        app_urls: [],
        name: 'TEST PROJECT',
        event_names: [],
        event_names_with_usage: [],
        event_properties: [],
        event_properties_with_usage: [],
        event_properties_numerical: [],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        anonymize_ips: false,
        completed_snippet_onboarding: true,
        ingested_event: true,
        uuid: new UUIDT().toString(),
        session_recording_opt_in: sessionRecordingOptIn,
        plugins_opt_in: false,
        opt_out_capture: false,
        is_demo: false,
        api_token: token ?? new UUIDT().toString(),
        test_account_filters: [],
        timezone: 'UTC',
        data_attributes: ['data-attr'],
        person_display_name_properties: [],
        access_control: false,
        slack_incoming_webhook,
    })
    return team.id
}

export const createAction = async (action: Omit<RawAction, 'id'>, steps: Omit<ActionStep, 'id' | 'action_id'>[]) => {
    const actionRow = await insertRow(postgres, 'posthog_action', action)
    for (const step of steps) {
        await insertRow(postgres, 'posthog_actionstep', {
            ...step,
            action_id: actionRow.id,
        })
    }
    return actionRow
}

export const createUser = async (teamId: number, email: string) => {
    return await insertRow(postgres, 'posthog_user', {
        password: 'abc',
        email,
        first_name: '',
        last_name: '',
        email_opt_in: false,
        distinct_id: email,
        is_staff: false,
        is_active: true,
        date_joined: new Date().toISOString(),
        events_column_config: '{}',
        uuid: new UUIDT().toString(),
    })
}

export async function createHook(teamId: number, userId: number, resourceId: number, target: string) {
    await insertRow(postgres, 'ee_hook', {
        id: new UUIDT().toString(),
        team_id: teamId,
        user_id: userId,
        resource_id: resourceId,
        event: 'action_performed',
        target: target,
        created: new Date().toISOString(),
        updated: new Date().toISOString(),
    } as Hook)
}

export const getPropertyDefinitions = async (teamId: number) => {
    const { rows } = await postgres.query(
        PostgresUse.COMMON_WRITE,
        `SELECT *
         FROM posthog_propertydefinition
         WHERE team_id = $1`,
        [teamId],
        'getPropertyDefinitions'
    )
    return rows
}

export const getMetric = async ({ name, type, labels }: Record<string, any>) => {
    // Requests `/_metrics` and extracts the value of the first metric we find
    // that matches name, type, and labels.
    //
    // Returns 0 if no metric is found.
    const openMetrics = await (await fetch('http://localhost:6738/_metrics')).text()
    return Number.parseFloat(
        parsePrometheusTextFormat(openMetrics)
            .filter((metric) => deepObjectContains(metric, { name, type }))[0]
            ?.metrics.filter((values) => deepObjectContains(values, { labels }))[0]?.value ?? 0
    )
}

const deepObjectContains = (obj: Record<string, any>, other: Record<string, any>): boolean => {
    // Returns true if `obj` contains all the keys in `other` and their values
    // are equal. If the values are objects, recursively checks if they contain
    // the keys in `other`.

    return Object.keys(other).every((key) => {
        if (typeof other[key] === 'object') {
            return deepObjectContains(obj[key], other[key])
        }
        return obj[key] === other[key]
    })
}
