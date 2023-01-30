import ClickHouse from '@posthog/clickhouse'
import Redis from 'ioredis'
import { Producer } from 'kafkajs'
import parsePrometheusTextFormat from 'parse-prometheus-text-format'
import { Pool } from 'pg'

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

export const capture = async (
    producer: Producer,
    teamId: number | null,
    distinctId: string,
    uuid: string,
    event: string,
    properties: object = {},
    token: string | null = null,
    sentAt: Date = new Date(),
    eventTime: Date = new Date(),
    now: Date = new Date(),
    topic = 'events_plugin_ingestion'
) => {
    // WARNING: this capture method is meant to simulate the ingestion of events
    // from the capture endpoint, but there is no guarantee that is is 100%
    // accurate.
    await producer.send({
        topic: topic,
        messages: [
            {
                key: teamId ? teamId.toString() : '',
                value: JSON.stringify({
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
                }),
            },
        ],
    })
}

export const createPlugin = async (pgClient: Pool, plugin: Omit<Plugin, 'id'>) => {
    return await insertRow(pgClient, 'posthog_plugin', {
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
    pgClient: Pool,
    pluginConfig: Omit<PluginConfig, 'id' | 'created_at' | 'enabled' | 'order' | 'config' | 'has_error'>
) => {
    return await insertRow(pgClient, 'posthog_pluginconfig', {
        ...pluginConfig,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        enabled: true,
        order: 0,
        config: {},
    })
}

export const createAndReloadPluginConfig = async (
    pgClient: Pool,
    teamId: number,
    pluginId: number,
    redis: Redis.Redis
) => {
    const pluginConfig = await createPluginConfig(pgClient, { team_id: teamId, plugin_id: pluginId })
    // Make sure the plugin server reloads the newly created plugin config.
    // TODO: avoid reaching into the pluginsServer internals and rather use
    // the pubsub mechanism to trigger this.
    await redis.publish('reload-plugins', '')
    return pluginConfig
}

export const reloadAction = async (redis: Redis.Redis, teamId: number, actionId: number) => {
    await redis.publish('reload-action', JSON.stringify({ teamId, actionId }))
}

export const fetchEvents = async (clickHouseClient: ClickHouse, teamId: number, uuid?: string) => {
    const queryResult = (await clickHouseClient.querying(`
        SELECT * FROM events 
        WHERE team_id = ${teamId} ${uuid ? `AND uuid = '${uuid}'` : ``} ORDER BY timestamp ASC
    `)) as unknown as ClickHouse.ObjectQueryResult<RawClickHouseEvent>
    return queryResult.data.map(parseRawClickHouseEvent)
}

export const fetchPersons = async (clickHouseClient: ClickHouse, teamId: number) => {
    const queryResult = (await clickHouseClient.querying(
        `SELECT * FROM person WHERE team_id = ${teamId} ORDER BY created_at ASC`
    )) as unknown as ClickHouse.ObjectQueryResult<any>
    return queryResult.data.map((person) => ({ ...person, properties: JSON.parse(person.properties) }))
}

export const fetchPostgresPersons = async (pgClient: Pool, teamId: number) => {
    const { rows } = await pgClient.query(`SELECT * FROM posthog_person WHERE team_id = $1`, [teamId])
    return rows
}

export const fetchSessionRecordingsEvents = async (clickHouseClient: ClickHouse, teamId: number, uuid?: string) => {
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

export const fetchPerformanceEvents = async (clickHouseClient: ClickHouse, teamId: number) => {
    const queryResult = (await clickHouseClient.querying(
        `SELECT * FROM performance_events WHERE team_id = ${teamId} ORDER BY timestamp ASC`
    )) as unknown as ClickHouse.ObjectQueryResult<RawPerformanceEvent>
    return queryResult.data
}

export const fetchPluginLogEntries = async (clickHouseClient: ClickHouse, pluginConfigId: number) => {
    const { data: logEntries } = (await clickHouseClient.querying(`
        SELECT * FROM plugin_log_entries
        WHERE plugin_config_id = ${pluginConfigId} AND source = 'CONSOLE'
    `)) as unknown as ClickHouse.ObjectQueryResult<PluginLogEntry>
    return logEntries.map((entry) => ({ ...entry, message: JSON.parse(entry.message) }))
}

export const createOrganization = async (pgClient: Pool) => {
    const organizationId = new UUIDT().toString()
    await insertRow(pgClient, 'posthog_organization', {
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
    pgClient: Pool,
    organizationId: string,
    slack_incoming_webhook?: string,
    token?: string,
    sessionRecordingOptIn = true
) => {
    const team = await insertRow(pgClient, 'posthog_team', {
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

export const createAction = async (
    pgClient: Pool,
    action: Omit<RawAction, 'id'>,
    steps: Omit<ActionStep, 'id' | 'action_id'>[]
) => {
    const actionRow = await insertRow(pgClient, 'posthog_action', action)
    for (const step of steps) {
        await insertRow(pgClient, 'posthog_actionstep', {
            ...step,
            action_id: actionRow.id,
        })
    }
    return actionRow
}

export const createUser = async (pgClient: Pool, teamId: number, email: string) => {
    return await insertRow(pgClient, 'posthog_user', {
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

export const getPropertyDefinitions = async (pgClient: Pool, teamId: number) => {
    const { rows } = await pgClient.query(`SELECT * FROM posthog_propertydefinition WHERE team_id = $1`, [teamId])
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
