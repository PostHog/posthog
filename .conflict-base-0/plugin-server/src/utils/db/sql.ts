import { Hub, Plugin, PluginAttachmentDB, PluginCapabilities, PluginConfig, PluginConfigId } from '../../types'
import { InlinePluginDescription } from '../../worker/vm/inline/inline'
import { PostgresUse } from './postgres'

function pluginConfigsInForceQuery(specificField?: keyof PluginConfig): string {
    const fields = specificField
        ? `posthog_pluginconfig.${specificField}`
        : `
        posthog_pluginconfig.id,
        posthog_pluginconfig.team_id,
        posthog_pluginconfig.plugin_id,
        posthog_pluginconfig.enabled,
        posthog_pluginconfig.order,
        posthog_pluginconfig.config,
        posthog_pluginconfig.filters,
        posthog_pluginconfig.updated_at,
        posthog_pluginconfig.created_at
    `

    return `SELECT ${fields}
       FROM posthog_pluginconfig
       LEFT JOIN posthog_team ON posthog_team.id = posthog_pluginconfig.team_id
       LEFT JOIN posthog_organization ON posthog_organization.id = posthog_team.organization_id
       LEFT JOIN posthog_plugin ON posthog_plugin.id = posthog_pluginconfig.plugin_id
       WHERE (
           posthog_pluginconfig.enabled='t'
           AND (posthog_pluginconfig.deleted is NULL OR posthog_pluginconfig.deleted!='t')
           AND posthog_organization.plugins_access_level > 0
       )`
}

const PLUGIN_SELECT = `SELECT
            posthog_plugin.id,
            posthog_plugin.name,
            posthog_plugin.url,
            posthog_plugin.tag,
            posthog_plugin.from_json,
            posthog_plugin.from_web,
            posthog_plugin.error,
            posthog_plugin.plugin_type,
            posthog_plugin.organization_id,
            posthog_plugin.is_global,
            posthog_plugin.capabilities,
            posthog_plugin.is_stateless,
            posthog_plugin.log_level,
            posthog_plugin.updated_at,
            psf__plugin_json.source as source__plugin_json,
            psf__index_ts.source as source__index_ts,
            psf__frontend_tsx.source as source__frontend_tsx,
            psf__site_ts.source as source__site_ts
        FROM posthog_plugin
        LEFT JOIN posthog_pluginsourcefile psf__plugin_json
            ON (psf__plugin_json.plugin_id = posthog_plugin.id AND psf__plugin_json.filename = 'plugin.json')
        LEFT JOIN posthog_pluginsourcefile psf__index_ts
            ON (psf__index_ts.plugin_id = posthog_plugin.id AND psf__index_ts.filename = 'index.ts')
        LEFT JOIN posthog_pluginsourcefile psf__frontend_tsx
            ON (psf__frontend_tsx.plugin_id = posthog_plugin.id AND psf__frontend_tsx.filename = 'frontend.tsx')
        LEFT JOIN posthog_pluginsourcefile psf__site_ts
            ON (psf__site_ts.plugin_id = posthog_plugin.id AND psf__site_ts.filename = 'site.ts')`

const PLUGIN_UPSERT_RETURNING = `INSERT INTO posthog_plugin
    (
        name,
        url,
        tag,
        from_json,
        from_web,
        error,
        plugin_type,
        organization_id,
        is_global,
        capabilities,
        is_stateless,
        log_level,
        description,
        is_preinstalled,
        config_schema,
        updated_at,
        created_at
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, NOW(), NOW())
    ON CONFLICT (url)
    DO UPDATE SET
        name = $1,
        tag = $3,
        from_json = $4,
        from_web = $5,
        error = $6,
        plugin_type = $7,
        organization_id = $8,
        is_global = $9,
        capabilities = $10,
        is_stateless = $11,
        log_level = $12,
        description = $13,
        is_preinstalled = $14,
        config_schema = $15,
        updated_at = NOW()
    RETURNING *
`

export async function getPlugin(hub: Hub, pluginId: number): Promise<Plugin | undefined> {
    const result = await hub.db.postgres.query(
        PostgresUse.COMMON_READ,
        `${PLUGIN_SELECT} WHERE posthog_plugin.id = $1`,
        [pluginId],
        'getPlugin'
    )
    return result.rows[0]
}

export async function getActivePluginRows(hub: Hub): Promise<Plugin[]> {
    const { rows }: { rows: Plugin[] } = await hub.db.postgres.query(
        PostgresUse.COMMON_READ,
        `${PLUGIN_SELECT}
        WHERE posthog_plugin.id IN (${pluginConfigsInForceQuery('plugin_id')}
        GROUP BY posthog_pluginconfig.plugin_id)`,
        undefined,
        'getActivePluginRows'
    )

    return rows
}

export async function getPluginAttachmentRows(hub: Hub): Promise<PluginAttachmentDB[]> {
    const { rows }: { rows: PluginAttachmentDB[] } = await hub.db.postgres.query(
        PostgresUse.COMMON_READ,
        `SELECT posthog_pluginattachment.* FROM posthog_pluginattachment
            WHERE plugin_config_id IN (${pluginConfigsInForceQuery('id')})`,
        undefined,
        'getPluginAttachmentRows'
    )
    return rows
}

export async function getPluginConfigRows(hub: Hub): Promise<PluginConfig[]> {
    const { rows }: { rows: PluginConfig[] } = await hub.db.postgres.query(
        PostgresUse.COMMON_READ,
        pluginConfigsInForceQuery(),
        undefined,
        'getPluginConfigRows'
    )
    return rows
}

export async function setPluginCapabilities(
    hub: Hub,
    pluginId: number,
    capabilities: PluginCapabilities
): Promise<void> {
    await hub.db.postgres.query(
        PostgresUse.COMMON_WRITE,
        'UPDATE posthog_plugin SET capabilities = ($1) WHERE id = $2',
        [capabilities, pluginId],
        'setPluginCapabilities'
    )
}

export async function disablePlugin(hub: Hub, pluginConfigId: PluginConfigId): Promise<void> {
    await hub.db.postgres.query(
        PostgresUse.COMMON_WRITE,
        `UPDATE posthog_pluginconfig SET enabled='f' WHERE id=$1 AND enabled='t'`,
        [pluginConfigId],
        'disablePlugin'
    )
    await hub.db.redisPublish('reload-plugins', '')
}

// Given an inline plugin description, upsert it into the known plugins table, returning the full
// Plugin object. Matching is done based on plugin url, not id, since that varies by region.
export async function upsertInlinePlugin(hub: Hub, inline: InlinePluginDescription): Promise<Plugin> {
    const fullPlugin: Plugin = {
        id: 0,
        name: inline.name,
        url: inline.url,
        tag: inline.tag,
        from_json: false,
        from_web: false,
        error: undefined,
        plugin_type: 'inline',
        organization_id: undefined,
        is_global: inline.is_global,
        capabilities: inline.capabilities,
        is_stateless: inline.is_stateless,
        log_level: inline.log_level,
        description: inline.description,
        is_preinstalled: inline.is_preinstalled,
        config_schema: inline.config_schema,
    }

    const { rows }: { rows: Plugin[] } = await hub.db.postgres.query(
        PostgresUse.COMMON_WRITE,
        `${PLUGIN_UPSERT_RETURNING}`,
        [
            fullPlugin.name,
            fullPlugin.url,
            fullPlugin.tag,
            fullPlugin.from_json,
            fullPlugin.from_web,
            fullPlugin.error,
            fullPlugin.plugin_type,
            fullPlugin.organization_id,
            fullPlugin.is_global,
            fullPlugin.capabilities,
            fullPlugin.is_stateless,
            fullPlugin.log_level,
            fullPlugin.description,
            fullPlugin.is_preinstalled,
            JSON.stringify(fullPlugin.config_schema),
        ],
        'upsertInlinePlugin'
    )

    return rows[0]
}
