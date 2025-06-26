import { DateTime } from 'luxon'

import { defaultConfig } from '../../src/config/config'
import {
    CookielessServerHashMode,
    Hub,
    InternalPerson,
    Plugin,
    PluginAttachmentDB,
    PluginConfig,
    PluginsServerConfig,
    ProjectId,
    PropertyOperator,
    RawAction,
    RawOrganization,
    RawPerson,
    Team,
} from '../../src/types'
import { DB } from '../../src/utils/db/db'
import { PostgresRouter, PostgresUse } from '../../src/utils/db/postgres'
import { UUIDT } from '../../src/utils/utils'
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

export const POSTGRES_DELETE_OTHER_TABLES_QUERY = `
DO $$
DECLARE
    r RECORD;
BEGIN
    -- First handle tables with foreign key dependencies
    DELETE FROM posthog_featureflaghashkeyoverride CASCADE;
    DELETE FROM posthog_cohortpeople CASCADE;
    DELETE FROM posthog_cohort CASCADE;
    DELETE FROM posthog_featureflag CASCADE;
    DELETE FROM posthog_organizationmembership CASCADE;
    DELETE FROM posthog_grouptypemapping CASCADE;
    DELETE FROM posthog_project CASCADE;
    DELETE FROM posthog_pluginsourcefile CASCADE;
    DELETE FROM posthog_pluginconfig CASCADE;
    DELETE FROM posthog_plugin CASCADE;
    DELETE FROM posthog_organization CASCADE;
    DELETE FROM posthog_action CASCADE;
    DELETE FROM posthog_user CASCADE;
    DELETE FROM posthog_group CASCADE;
    DELETE FROM posthog_persondistinctid CASCADE;
    DELETE FROM posthog_person CASCADE;
    DELETE FROM posthog_team CASCADE;
    
    -- Then handle remaining tables
    FOR r IN (
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = current_schema()
        AND tablename NOT IN (
            'posthog_featureflaghashkeyoverride',
            'posthog_cohortpeople',
            'posthog_cohort',
            'posthog_featureflag',
            'posthog_organizationmembership',
            'posthog_grouptypemapping',
            'posthog_project',
            'posthog_pluginsourcefile',
            'posthog_pluginconfig',
            'posthog_plugin',
            'posthog_organization',
            'posthog_action',
            'posthog_user',
            'posthog_group',
            'posthog_persondistinctid',
            'posthog_person',
            'posthog_team'
        )
    ) LOOP
        EXECUTE 'DELETE FROM ' || quote_ident(r.tablename) || ' CASCADE';
    END LOOP;
END $$;
`

export async function clearDatabase(db: PostgresRouter) {
    // Delete all tables using COMMON_WRITE
    await db
        .query(PostgresUse.COMMON_WRITE, POSTGRES_DELETE_OTHER_TABLES_QUERY, undefined, 'delete-other-tables')
        .catch((e) => {
            console.error('Error deleting other tables', e)
            throw e
        })
}

// TODO: This shouldn't be called resetTestDatabase, as it actually adds data to the database
// which can be misleading for people running tests
export async function resetTestDatabase(
    code?: string,
    extraServerConfig: Partial<PluginsServerConfig> = {},
    extraRows: ExtraDatabaseRows = {},
    { withExtendedTestData = true }: { withExtendedTestData?: boolean } = {}
): Promise<void> {
    const config = { ...defaultConfig, ...extraServerConfig, POSTGRES_CONNECTION_POOL_SIZE: 1 }
    const db = new PostgresRouter(config)

    // Delete all tables using COMMON_WRITE
    await db
        .query(PostgresUse.COMMON_WRITE, POSTGRES_DELETE_OTHER_TABLES_QUERY, undefined, 'delete-other-tables')
        .catch((e) => {
            console.error('Error deleting other tables', e)
            throw e
        })

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
            steps_json: [
                {
                    tag_name: null,
                    text: null,
                    href: null,
                    selector: null,
                    url: null,
                    url_matching: null,
                    event: null,
                    properties: [{ type: 'event', operator: PropertyOperator.Exact, key: 'foo', value: ['bar'] }],
                },
            ],
        } as RawAction)
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

export async function insertRow(db: PostgresRouter, table: string, objectProvided: Record<string, any>) {
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
        } = await db.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO ${table} (${keys})
             VALUES (${params})
             RETURNING *`,
            values,
            `insertRow-${table}`
        )
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
    db: PostgresRouter,
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
        available_product_features: [],
        domain_whitelist: [],
        is_member_join_email_enabled: false,
        slug: new UUIDT().toString(),
    } as RawOrganization)
    await updateOrganizationAvailableFeatures(db, organizationId, [{ key: 'data_pipelines', name: 'Data Pipelines' }])
    await insertRow(db, 'posthog_organizationmembership', {
        id: organizationMembershipId,
        organization_id: organizationId,
        user_id: userId,
        level: 15,
        joined_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
    })
    await insertRow(db, 'posthog_project', {
        id: teamId,
        organization_id: organizationId,
        name: 'TEST PROJECT',
        created_at: new Date().toISOString(),
    })
    await insertRow(db, 'posthog_team', {
        id: teamId,
        project_id: teamId,
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
        base_currency: 'USD',
        cookieless_server_hash_mode: CookielessServerHashMode.Stateful,
    })
}

export async function getTeams(hub: Hub): Promise<Team[]> {
    const selectResult = await hub.postgres.query<Team>(
        PostgresUse.COMMON_READ,
        'SELECT * FROM posthog_team ORDER BY id',
        undefined,
        'fetchAllTeams'
    )
    for (const row of selectResult.rows) {
        row.project_id = parseInt(row.project_id as unknown as string) as ProjectId
    }
    return selectResult.rows
}

export async function getTeam(hub: Hub, teamId: Team['id']): Promise<Team | null> {
    const teams = await getTeams(hub)
    return teams.find((team) => team.id === teamId) ?? null
}

export async function getFirstTeam(hub: Hub): Promise<Team> {
    return (await getTeams(hub))[0]
}

export const createPlugin = async (pg: PostgresRouter, plugin: Omit<Plugin, 'id'>) => {
    return await insertRow(pg, 'posthog_plugin', {
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
    pg: PostgresRouter,
    pluginConfig: Omit<PluginConfig, 'id' | 'created_at' | 'enabled' | 'order' | 'config'>
) => {
    return await insertRow(pg, 'posthog_pluginconfig', {
        ...pluginConfig,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        enabled: true,
        order: 0,
        config: {},
    })
}

export const createOrganization = async (pg: PostgresRouter) => {
    const organizationId = new UUIDT().toString()
    await insertRow(pg, 'posthog_organization', {
        id: organizationId,
        name: 'TEST ORG',
        plugins_access_level: 9,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        personalization: '{}', // DEPRECATED
        setup_section_2_completed: true, // DEPRECATED
        for_internal_metrics: false,
        available_product_features: [],
        domain_whitelist: [],
        is_member_join_email_enabled: false,
        slug: new UUIDT().toString(),
    })
    return organizationId
}

export const updateOrganizationAvailableFeatures = async (
    pg: PostgresRouter,
    organizationId: string,
    features: { key: string; name: string }[]
) => {
    await pg.query(
        PostgresUse.COMMON_WRITE,
        `UPDATE posthog_organization SET available_product_features = $1 WHERE id = $2`,
        [features, organizationId],
        'change-team-available-features'
    )
}

export const createTeam = async (
    pg: PostgresRouter,
    projectOrOrganizationId: ProjectId | string,
    token?: string
): Promise<number> => {
    // KLUDGE: auto increment IDs can be racy in tests so we ensure IDs don't clash
    const id = Math.round(Math.random() * 1000000000)
    let organizationId: string
    let projectId: ProjectId
    if (typeof projectOrOrganizationId === 'number') {
        projectId = projectOrOrganizationId
        organizationId = await pg
            .query<{ organization_id: string }>(
                PostgresUse.COMMON_READ,
                'SELECT organization_id FROM posthog_project WHERE id = $1',
                [projectId],
                'fetchOrganizationId'
            )
            .then((result) => result.rows[0].organization_id)
    } else {
        projectId = id as ProjectId
        organizationId = projectOrOrganizationId
        await insertRow(pg, 'posthog_project', {
            // Every team (aka environment) must be a child of a project
            id,
            organization_id: organizationId,
            name: 'TEST PROJECT',
            created_at: new Date().toISOString(),
        })
    }
    await insertRow(pg, 'posthog_team', {
        id,
        organization_id: organizationId,
        project_id: projectId,
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
        base_currency: 'USD',
    })
    return id
}

export const createUser = async (pg: PostgresRouter, distinctId: string) => {
    const uuid = new UUIDT().toString()
    const user = await insertRow(pg, 'posthog_user', {
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

export const createOrganizationMembership = async (pg: PostgresRouter, organizationId: string, userId: number) => {
    const membershipId = new UUIDT().toString()
    const membership = await insertRow(pg, 'posthog_organizationmembership', {
        id: membershipId,
        organization_id: organizationId,
        user_id: userId,
        level: 15,
        joined_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
    })
    return membership.id
}

export async function fetchPostgresPersons(db: DB, teamId: number) {
    const query = `SELECT * FROM posthog_person WHERE team_id = ${teamId} ORDER BY id`
    return (await db.postgres.query(PostgresUse.PERSONS_READ, query, undefined, 'persons')).rows.map(
        // NOTE: we map to update some values here to maintain
        // compatibility with `hub.db.fetchPersons`.
        // TODO: remove unnecessary property translation operation.
        (rawPerson: RawPerson) =>
            ({
                ...rawPerson,
                created_at: DateTime.fromISO(rawPerson.created_at).toUTC(),
                version: Number(rawPerson.version || 0),
            } as InternalPerson)
    )
}
