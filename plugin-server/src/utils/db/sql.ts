import {
    Hub,
    Plugin,
    PluginAttachmentDB,
    PluginCapabilities,
    PluginConfig,
    PluginConfigId,
    PluginError,
    PluginLogEntrySource,
    PluginLogEntryType,
    StoredPluginMetrics,
} from '../../types'

function pluginConfigsInForceQuery(specificField?: keyof PluginConfig): string {
    return `SELECT posthog_pluginconfig.${specificField || '*'}
       FROM posthog_pluginconfig
       LEFT JOIN posthog_team ON posthog_team.id = posthog_pluginconfig.team_id
       LEFT JOIN posthog_organization ON posthog_organization.id = posthog_team.organization_id
       LEFT JOIN posthog_plugin ON posthog_plugin.id = posthog_pluginconfig.plugin_id
       WHERE (
           posthog_pluginconfig.enabled='t' AND posthog_organization.plugins_access_level > 0
           AND (posthog_plugin.organization_id = posthog_organization.id OR posthog_plugin.is_global)
       )`
}

export async function getPluginRows(hub: Hub): Promise<Plugin[]> {
    const { rows }: { rows: Plugin[] } = await hub.db.postgresQuery(
        // `posthog_plugin` columns have to be listed individually, as we want to exclude the blob `archive` column,
        // and Postgres unfortunately doesn't have a feature to exclude a single column from *
        `SELECT
            posthog_plugin.id,
            posthog_plugin.name,
            posthog_plugin.description,
            posthog_plugin.url,
            posthog_plugin.config_schema,
            posthog_plugin.tag,
            posthog_plugin.from_json,
            posthog_plugin.from_web,
            posthog_plugin.error,
            posthog_plugin.plugin_type,
            posthog_plugin.source,
            posthog_plugin.organization_id,
            posthog_plugin.latest_tag,
            posthog_plugin.latest_tag_checked_at,
            posthog_plugin.created_at,
            posthog_plugin.updated_at,
            posthog_plugin.is_global,
            posthog_plugin.is_preinstalled,
            posthog_plugin.capabilities,
            posthog_plugin.metrics,
            posthog_plugin.public_jobs,
            posthog_plugin.is_stateless,
            posthog_plugin.log_level,
            psf__plugin_json.source as source__plugin_json,
            psf__index_ts.source as source__index_ts,
            psf__frontend_tsx.source as source__frontend_tsx
        FROM posthog_plugin
        LEFT JOIN posthog_pluginsourcefile psf__plugin_json
            ON (psf__plugin_json.plugin_id = posthog_plugin.id AND psf__plugin_json.filename = 'plugin.json')
        LEFT JOIN posthog_pluginsourcefile psf__index_ts
            ON (psf__index_ts.plugin_id = posthog_plugin.id AND psf__index_ts.filename = 'index.ts')
        LEFT JOIN posthog_pluginsourcefile psf__frontend_tsx
            ON (psf__frontend_tsx.plugin_id = posthog_plugin.id AND psf__frontend_tsx.filename = 'frontend.tsx')
        WHERE posthog_plugin.id IN (${pluginConfigsInForceQuery('plugin_id')}
        GROUP BY posthog_pluginconfig.plugin_id)`,
        undefined,
        'getPluginRows'
    )

    return rows
}

export async function getPluginAttachmentRows(hub: Hub): Promise<PluginAttachmentDB[]> {
    const { rows }: { rows: PluginAttachmentDB[] } = await hub.db.postgresQuery(
        `SELECT posthog_pluginattachment.* FROM posthog_pluginattachment
            WHERE plugin_config_id IN (${pluginConfigsInForceQuery('id')})`,
        undefined,
        'getPluginAttachmentRows'
    )
    return rows
}

export async function getPluginConfigRows(hub: Hub): Promise<PluginConfig[]> {
    const { rows }: { rows: PluginConfig[] } = await hub.db.postgresQuery(
        pluginConfigsInForceQuery(),
        undefined,
        'getPluginConfigRows'
    )
    return rows
}

export async function setPluginCapabilities(
    hub: Hub,
    pluginConfig: PluginConfig,
    capabilities: PluginCapabilities
): Promise<void> {
    await hub.db.postgresQuery(
        'UPDATE posthog_plugin SET capabilities = ($1) WHERE id = $2',
        [capabilities, pluginConfig.plugin_id],
        'setPluginCapabilities'
    )
}

export async function setPluginMetrics(
    hub: Hub,
    pluginConfig: PluginConfig,
    metrics: StoredPluginMetrics
): Promise<void> {
    await hub.db.postgresQuery(
        'UPDATE posthog_plugin SET metrics = ($1) WHERE id = $2',
        [metrics, pluginConfig.plugin_id],
        'setPluginMetrics'
    )
}

export async function setError(hub: Hub, pluginError: PluginError | null, pluginConfig: PluginConfig): Promise<void> {
    await hub.db.postgresQuery(
        'UPDATE posthog_pluginconfig SET error = $1 WHERE id = $2',
        [pluginError, typeof pluginConfig === 'object' ? pluginConfig?.id : pluginConfig],
        'updatePluginConfigError'
    )
    if (pluginError) {
        await hub.db.queuePluginLogEntry({
            pluginConfig,
            source: PluginLogEntrySource.Plugin,
            type: PluginLogEntryType.Error,
            message: pluginError.stack ?? pluginError.message,
            instanceId: hub.instanceId,
            timestamp: pluginError.time,
        })
    }
}

export async function disablePlugin(hub: Hub, pluginConfigId: PluginConfigId): Promise<void> {
    await hub.db.postgresQuery(
        `UPDATE posthog_pluginconfig SET enabled='f' WHERE id=$1 AND enabled='t'`,
        [pluginConfigId],
        'disablePlugin'
    )
    await hub.db.redisPublish(hub.PLUGINS_RELOAD_PUBSUB_CHANNEL, 'reload!')
}
