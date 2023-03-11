import { Client } from 'pg'
import { v4 } from 'uuid'

import { defaultConfig } from '../../src/config/config'
import {
    Hub,
    Plugin,
    PluginAttachmentDB,
    PluginConfig,
    PropertyOperator,
    RawAction,
    RawOrganization,
    Team,
} from '../../src/types'
import { UUIDT } from '../../src/utils/utils'
import { makePluginObjects } from './plugins'

let postgres: Client
let pluginConfigIds: number[] = []

beforeAll(async () => {
    postgres = new Client({ connectionString: defaultConfig.DATABASE_URL! })
    await postgres.connect()
})

beforeEach(() => {
    pluginConfigIds = []
})

afterEach(async () => {
    // Disable any plugins created by the current test
    await postgres.query('UPDATE posthog_pluginconfig SET enabled = FALSE WHERE id = ANY($1)', [pluginConfigIds])
})

afterAll(async () => {
    await postgres?.end()
})

export interface ExtraDatabaseRows {
    plugins?: Omit<Plugin, 'id'>[]
    pluginConfigs?: Omit<PluginConfig, 'id'>[]
    pluginAttachments?: Omit<PluginAttachmentDB, 'id'>[]
}

export async function resetTestDatabase(
    code?: string,
    { withExtendedTestData = false }: { withExtendedTestData?: boolean } = {}
) {
    const mocks = makePluginObjects(code)
    const { team, teamId, organizationId, apiToken, teamUuid, userId } = await createUserTeamAndOrganization({})
    if (withExtendedTestData) {
        const { id: actionId } = await insertRow('posthog_action', {
            team_id: teamId,
            name: 'Test Action',
            description: '',
            created_at: new Date().toISOString(),
            created_by_id: userId,
            deleted: false,
            post_to_slack: true,
            slack_message_format: '',
            is_calculating: false,
            updated_at: new Date().toISOString(),
            last_calculated_at: new Date().toISOString(),
        } as RawAction)
        const { id: actionStepId } = await insertRow('posthog_actionstep', {
            action_id: actionId,
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
        const plugin = await createPlugin({
            ...mocks.pluginRow,
            name: `Test plugin teamId=${teamId} orgId=${organizationId}`,
            organization_id: organizationId,
        })
        const pluginConfig = await createPluginConfig({
            ...mocks.pluginConfigRow,
            team_id: teamId,
            plugin_id: plugin.id,
        })
        const pluginAttachment = await createPluginAttachment({
            ...mocks.pluginAttachmentRow,
            plugin_config_id: pluginConfig.id,
            team_id: teamId,
        })

        return {
            team,
            teamId,
            teamUuid,
            userId,
            organizationId,
            pluginId: plugin.id,
            plugin,
            pluginConfigId: pluginConfig.id,
            pluginConfig,
            pluginAttachmentId: pluginAttachment.id,
            pluginAttachment,
            apiToken,
            actionId,
            actionStepId,
        }
    }
    return { team, teamId, teamUuid, userId, organizationId, apiToken }
}

async function createPluginAttachment(pluginAttachment: Omit<PluginAttachmentDB, 'id'>) {
    return await insertRow('posthog_pluginattachment', pluginAttachment)
}

export async function insertRow(table: string, objectProvided: Record<string, any>) {
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
        } = await postgres.query(`INSERT INTO ${table} (${keys}) VALUES (${params}) RETURNING *`, values)
        const dependentQueries: Promise<void>[] = []
        if (source__plugin_json) {
            dependentQueries.push(
                insertRow('posthog_pluginsourcefile', {
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
                insertRow('posthog_pluginsourcefile', {
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
                insertRow('posthog_pluginsourcefile', {
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
                insertRow('posthog_pluginsourcefile', {
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

export async function createUserTeamAndOrganization({
    userUuid = v4(),
    organizationId = v4(),
    organizationMembershipId = v4(),
}: {
    userUuid?: string
    organizationId?: string
    organizationMembershipId?: string
}) {
    const { id: userId } = await insertRow('posthog_user', {
        uuid: userUuid,
        password: 'gibberish',
        first_name: 'PluginTest',
        last_name: 'User',
        email: `test${userUuid}@posthog.com`,
        distinct_id: `plugin_test_user_distinct_id_${userUuid}`,
        is_staff: false,
        is_active: false,
        date_joined: new Date().toISOString(),
        events_column_config: { active: 'DEFAULT' },
    })
    await insertRow('posthog_organization', {
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
        slug: v4(),
    } as RawOrganization)
    await insertRow('posthog_organizationmembership', {
        id: organizationMembershipId,
        organization_id: organizationId,
        user_id: userId,
        level: 15,
        joined_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
    })
    const team = await insertRow('posthog_team', {
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
        api_token: `THIS IS NOT A TOKEN FOR TEAM ${organizationId}`,
        test_account_filters: [],
        timezone: 'UTC',
        data_attributes: ['data-attr'],
        person_display_name_properties: [],
        access_control: false,
    })

    return {
        team,
        teamId: team.id,
        organizationId,
        userId,
        organizationMembershipId,
        apiToken: team.api_token,
        teamUuid: team.uuid,
    }
}

export async function getTeams(hub: Hub): Promise<Team[]> {
    return (await hub.db.postgresQuery('SELECT * FROM posthog_team ORDER BY id', undefined, 'fetchAllTeams')).rows
}

export async function getErrorForPluginConfig(id: number): Promise<any> {
    let error
    try {
        const response = await postgres.query('SELECT * FROM posthog_pluginconfig WHERE id = $1', [id])
        error = response.rows[0]['error']
    } catch {}

    return error
}

export const createPlugin = async (plugin: Omit<Plugin, 'id'>) => {
    return await insertRow('posthog_plugin', {
        config_schema: {},
        from_json: false,
        from_web: false,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        is_preinstalled: false,
        capabilities: {},
        ...plugin,
    })
}

export const createPluginConfig = async (
    pluginConfig: Omit<PluginConfig, 'id' | 'created_at' | 'enabled' | 'order' | 'config' | 'has_error'>
) => {
    const pc = await insertRow('posthog_pluginconfig', {
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        enabled: true,
        order: 0,
        config: {},
        ...pluginConfig,
    })
    pluginConfigIds.push(pc.id)
    return pc
}

export const createOrganization = async () => {
    const organizationId = new UUIDT().toString()
    await insertRow('posthog_organization', {
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
        slug: new UUIDT().toString(),
    })
    return organizationId
}

export const createTeam = async (organizationId: string, token?: string) => {
    const team = await insertRow('posthog_team', {
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

export const createUser = async (distinctId: string) => {
    const uuid = new UUIDT().toString()
    const user = await insertRow('posthog_user', {
        uuid: uuid,
        password: 'gibberish',
        first_name: 'PluginTest',
        last_name: 'User',
        email: `test${uuid}@posthog.com`,
        distinct_id: distinctId,
        is_staff: false,
        is_active: false,
        date_joined: new Date().toISOString(),
        events_column_config: { active: 'DEFAULT' },
    })
    return user.id
}

export const createOrganizationMembership = async (organizationId: string, userId: number) => {
    const membershipId = new UUIDT().toString()
    const membership = await insertRow('posthog_organizationmembership', {
        id: membershipId,
        organization_id: organizationId,
        user_id: userId,
        level: 15,
        joined_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
    })
    return membership.id
}
