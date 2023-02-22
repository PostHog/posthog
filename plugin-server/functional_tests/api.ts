import ClickHouse from '@posthog/clickhouse'
import Redis from 'ioredis'
import parsePrometheusTextFormat from 'parse-prometheus-text-format'
import { Pool } from 'pg'

import { defaultConfig } from '../src/config/config'
import {
    ActionStep,
    PluginLogEntry,
    RawAction,
    RawClickHouseEvent,
    RawPerformanceEvent,
    RawSessionRecordingEvent,
} from '../src/types'
import { Plugin, PluginConfig } from '../src/types'
import { parseRawClickHouseEvent } from '../src/utils/event'
import { UUIDT } from '../src/utils/utils'
import { insertRow } from '../tests/helpers/sql'
import { produce } from './kafka'

let clickHouseClient: ClickHouse
let postgres: Pool // NOTE: we use a Pool here but it's probably not necessary, but for instance `insertRow` uses a Pool.
let redis: Redis.Redis

beforeAll(() => {
    // Setup connections to kafka, clickhouse, and postgres
    postgres = new Pool({
        connectionString: defaultConfig.DATABASE_URL!,
        // We use a pool only for typings sake, but we don't actually need to,
        // so set max connections to 1.
        max: 1,
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
    topic = 'events_plugin_ingestion',
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
}) => {
    // WARNING: this capture method is meant to simulate the ingestion of events
    // from the capture endpoint, but there is no guarantee that is is 100%
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
                }),
            })
        ),
        key: teamId ? teamId.toString() : '',
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
    pluginConfig: Omit<PluginConfig, 'id' | 'created_at' | 'enabled' | 'order' | 'config' | 'has_error'>
) => {
    return await insertRow(postgres, 'posthog_pluginconfig', {
        ...pluginConfig,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        enabled: true,
        order: 0,
        config: {},
    })
}

export const createAndReloadPluginConfig = async (teamId: number, pluginId: number) => {
    const pluginConfig = await createPluginConfig({ team_id: teamId, plugin_id: pluginId })
    // Make sure the plugin server reloads the newly created plugin config.
    // TODO: avoid reaching into the pluginsServer internals and rather use
    // the pubsub mechanism to trigger this.
    await redis.publish('reload-plugins', '')
    return pluginConfig
}

export const reloadAction = async (teamId: number, actionId: number) => {
    await redis.publish('reload-action', JSON.stringify({ teamId, actionId }))
}

export const fetchEvents = async (teamId: number, uuid?: string) => {
    const queryResult = (await clickHouseClient.querying(`
        SELECT 
            *, 
            dictGetOrDefault(
                person_overrides_dict, 
                'override_person_id', 
                (${teamId}, events.person_id),
                events.person_id
            ) as person_id 
        FROM events 
        WHERE team_id = ${teamId} ${uuid ? `AND uuid = '${uuid}'` : ``} ORDER BY timestamp ASC
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
    const { rows } = await postgres.query(`SELECT * FROM posthog_person WHERE team_id = $1`, [teamId])
    return rows
}

export const fetchSessionRecordingsEvents = async (teamId: number, uuid?: string) => {
    const queryResult = (await clickHouseClient.querying(
        `SELECT * FROM session_recording_events WHERE team_id = ${teamId} ${
            uuid ? ` AND uuid = '${uuid}'` : ''
        } ORDER BY timestamp ASC`
    )) as unknown as ClickHouse.ObjectQueryResult<RawSessionRecordingEvent>
    return queryResult.data.map((event) => {
        return {
            ...event,
            snapshot_data: event.snapshot_data ? JSON.parse(event.snapshot_data) : null,
        }
    })
}

export const fetchPerformanceEvents = async (teamId: number) => {
    const queryResult = (await clickHouseClient.querying(
        `SELECT * FROM performance_events WHERE team_id = ${teamId} ORDER BY timestamp ASC`
    )) as unknown as ClickHouse.ObjectQueryResult<RawPerformanceEvent>
    return queryResult.data
}

export const fetchPluginLogEntries = async (pluginConfigId: number) => {
    const { data: logEntries } = (await clickHouseClient.querying(`
        SELECT * FROM plugin_log_entries
        WHERE plugin_config_id = ${pluginConfigId} AND source = 'CONSOLE'
    `)) as unknown as ClickHouse.ObjectQueryResult<PluginLogEntry>
    return logEntries.map((entry) => ({ ...entry, message: JSON.parse(entry.message) }))
}

export const createOrganization = async () => {
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

export const getPropertyDefinitions = async (teamId: number) => {
    const { rows } = await postgres.query(`SELECT * FROM posthog_propertydefinition WHERE team_id = $1`, [teamId])
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
