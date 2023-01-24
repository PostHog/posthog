import { createPool } from 'generic-pool'
import Redis from 'ioredis'
import { Pool, PoolClient } from 'pg'

import { defaultConfig } from '../../src/config/config'
import {
    Hub,
    Plugin,
    PluginAttachmentDB,
    PluginConfig,
    PluginsServerConfig,
    PropertyOperator,
    RawAction,
    RawOrganization,
    Team,
} from '../../src/types'
import { createRedis, UUIDT } from '../../src/utils/utils'
import {
    commonOrganizationId,
    commonOrganizationMembershipId,
    commonUserId,
    commonUserUuid,
    makePluginObjects,
} from './plugins'

export interface ExtraDatabaseRows {
    plugins?: Omit<Plugin, 'id'>[]
    pluginConfigs?: Omit<PluginConfig, 'id'>[]
    pluginAttachments?: Omit<PluginAttachmentDB, 'id'>[]
}

export const POSTGRES_DELETE_TABLES_QUERY = `
DO $$ DECLARE
  r RECORD;
BEGIN
  FOR r IN (SELECT tablename FROM pg_tables WHERE schemaname = current_schema()) LOOP
    EXECUTE 'DELETE FROM ' || quote_ident(r.tablename);
  END LOOP;
END $$;
`

export async function resetRedis(pluginServerConfig: PluginsServerConfig): Promise<void> {
    const redisPool = createPool<Redis.Redis>(
        {
            create: () => createRedis(pluginServerConfig),
            destroy: async (client) => {
                await client.quit()
            },
        },
        {
            autostart: true,
        }
    )
    const redis = await redisPool.acquire()
    await redis.flushdb()
    await redisPool.release(redis)
}

export async function resetTestDatabase(
    code?: string,
    extraServerConfig: Partial<PluginsServerConfig> = {},
    extraRows: ExtraDatabaseRows = {},
    { withExtendedTestData = true }: { withExtendedTestData?: boolean } = {}
): Promise<void> {
    const config = { ...defaultConfig, ...extraServerConfig }
    await resetRedis(config)

    const db = new Pool({ connectionString: config.DATABASE_URL!, max: 1 })

    await db.query(POSTGRES_DELETE_TABLES_QUERY)
    const mocks = makePluginObjects(code)
    const teamIds = mocks.pluginConfigRows.map((c) => c.team_id)
    const teamIdToCreate = teamIds[0]
    await createUserTeamAndOrganization(db, teamIdToCreate)
    if (withExtendedTestData) {
        await insertRow(db, 'posthog_action', {
            id: teamIdToCreate + 67,
            team_id: teamIdToCreate,
            name: 'Test Action',
            description: '',
            created_at: new Date().toISOString(),
            created_by_id: commonUserId,
            deleted: false,
            post_to_slack: true,
            slack_message_format: '',
            is_calculating: false,
            updated_at: new Date().toISOString(),
            last_calculated_at: new Date().toISOString(),
        } as RawAction)
        await insertRow(db, 'posthog_actionstep', {
            id: teamIdToCreate + 911,
            action_id: teamIdToCreate + 67,
            tag_name: null,
            text: null,
            href: null,
            selector: null,
            url: null,
            url_matching: null,
            name: null,
            event: null,
            properties: [{ type: 'event', operator: PropertyOperator.Exact, key: 'foo', value: ['bar'] }],
        })
        for (const plugin of mocks.pluginRows.concat(extraRows.plugins ?? [])) {
            await insertRow(db, 'posthog_plugin', plugin)
        }
        for (const pluginConfig of mocks.pluginConfigRows.concat(extraRows.pluginConfigs ?? [])) {
            await insertRow(db, 'posthog_pluginconfig', pluginConfig)
        }
        for (const pluginAttachment of mocks.pluginAttachmentRows.concat(extraRows.pluginAttachments ?? [])) {
            await insertRow(db, 'posthog_pluginattachment', pluginAttachment)
        }
    }
    await db.end()
}

export async function insertRow(db: Pool, table: string, objectProvided: Record<string, any>) {
    // Handling of related fields
    const { source__plugin_json, source__index_ts, source__frontend_tsx, source__site_ts, ...object } = objectProvided

    const keys = Object.keys(object)
        .map((key) => `"${key}"`)
        .join(',')
    const params = Object.keys(object)
        .map((_, i) => `\$${i + 1}`)
        .join(',')
    const values = Object.values(object).map((value) => {
        if (Array.isArray(value) && value.length > 0) {
            return JSON.stringify(value)
        }
        return value
    })

    try {
        const {
            rows: [rowSaved],
        } = await db.query(`INSERT INTO ${table} (${keys}) VALUES (${params}) RETURNING *`, values)
        const dependentQueries: Promise<void>[] = []
        if (source__plugin_json) {
            dependentQueries.push(
                insertRow(db, 'posthog_pluginsourcefile', {
                    id: new UUIDT().toString(),
                    filename: 'plugin.json',
                    source: source__plugin_json,
                    plugin_id: rowSaved.id,
                    error: null,
                    transpiled: null,
                })
            )
        }
        if (source__index_ts) {
            dependentQueries.push(
                insertRow(db, 'posthog_pluginsourcefile', {
                    id: new UUIDT().toString(),
                    filename: 'index.ts',
                    source: source__index_ts,
                    plugin_id: rowSaved.id,
                    error: null,
                    transpiled: null,
                })
            )
        }
        if (source__frontend_tsx) {
            dependentQueries.push(
                insertRow(db, 'posthog_pluginsourcefile', {
                    id: new UUIDT().toString(),
                    filename: 'frontend.tsx',
                    source: source__frontend_tsx,
                    plugin_id: rowSaved.id,
                    error: null,
                    transpiled: null,
                })
            )
        }
        if (source__site_ts) {
            dependentQueries.push(
                insertRow(db, 'posthog_pluginsourcefile', {
                    id: new UUIDT().toString(),
                    filename: 'site.ts',
                    source: source__site_ts,
                    plugin_id: rowSaved.id,
                    error: null,
                    transpiled: null,
                })
            )
        }
        await Promise.all(dependentQueries)
        return rowSaved
    } catch (error) {
        console.error(`Error on table ${table} when inserting object:\n`, object, '\n', error)
        throw error
    }
}

export async function createUserTeamAndOrganization(
    db: Pool,
    teamId: number,
    userId: number = commonUserId,
    userUuid: string = commonUserUuid,
    organizationId: string = commonOrganizationId,
    organizationMembershipId: string = commonOrganizationMembershipId
): Promise<void> {
    await insertRow(db, 'posthog_user', {
        id: userId,
        uuid: userUuid,
        password: 'gibberish',
        first_name: 'PluginTest',
        last_name: 'User',
        email: `test${userId}@posthog.com`,
        distinct_id: `plugin_test_user_distinct_id_${userId}`,
        is_staff: false,
        is_active: false,
        date_joined: new Date().toISOString(),
        events_column_config: { active: 'DEFAULT' },
    })
    await insertRow(db, 'posthog_organization', {
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
        slug: Math.round(Math.random() * 10000),
    } as RawOrganization)
    await insertRow(db, 'posthog_organizationmembership', {
        id: organizationMembershipId,
        organization_id: organizationId,
        user_id: userId,
        level: 15,
        joined_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
    })
    await insertRow(db, 'posthog_team', {
        id: teamId,
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
        session_recording_opt_in: true,
        plugins_opt_in: false,
        opt_out_capture: false,
        is_demo: false,
        api_token: `THIS IS NOT A TOKEN FOR TEAM ${teamId}`,
        test_account_filters: [],
        timezone: 'UTC',
        data_attributes: ['data-attr'],
        person_display_name_properties: [],
        access_control: false,
    })
}

export async function getTeams(hub: Hub): Promise<Team[]> {
    return (await hub.db.postgresQuery('SELECT * FROM posthog_team ORDER BY id', undefined, 'fetchAllTeams')).rows
}

export async function getFirstTeam(hub: Hub): Promise<Team> {
    return (await getTeams(hub))[0]
}

/** Inject code onto `server` which runs a callback whenever a postgres query is performed */
export function onQuery(hub: Hub, onQueryCallback: (queryText: string) => any): void {
    function spyOnQueryFunction(client: any) {
        const query = client.query.bind(client)
        client.query = (queryText: any, values?: any, callback?: any): any => {
            onQueryCallback(queryText)
            return query(queryText, values, callback)
        }
    }

    spyOnQueryFunction(hub.postgres)

    const postgresTransaction = hub.db.postgresTransaction.bind(hub.db)
    hub.db.postgresTransaction = async (
        tag: string,
        transaction: (client: PoolClient) => Promise<any>
    ): Promise<any> => {
        return await postgresTransaction(tag, async (client: PoolClient) => {
            const query = client.query
            spyOnQueryFunction(client)
            const response = await transaction(client)
            client.query = query
            return response
        })
    }
}

export async function getErrorForPluginConfig(id: number): Promise<any> {
    const db = new Pool({ connectionString: defaultConfig.DATABASE_URL! })
    let error
    try {
        const response = await db.query('SELECT * FROM posthog_pluginconfig WHERE id = $1', [id])
        error = response.rows[0]['error']
    } catch {}

    await db.end()
    return error
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

export const createTeam = async (pgClient: Pool, organizationId: string, token?: string) => {
    const team = await insertRow(pgClient, 'posthog_team', {
        // KLUDGE: auto increment IDs can be racy in tests so we ensure IDs don't clash
        id: Math.round(Math.random() * 1000000000),
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
        session_recording_opt_in: true,
        plugins_opt_in: false,
        opt_out_capture: false,
        is_demo: false,
        api_token: token ?? new UUIDT().toString(),
        test_account_filters: [],
        timezone: 'UTC',
        data_attributes: ['data-attr'],
        person_display_name_properties: [],
        access_control: false,
    })
    return team.id
}
