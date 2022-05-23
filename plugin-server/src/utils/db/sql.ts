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
        `SELECT
            posthog_plugin.*,
            psf__index_ts.source as source__index_ts,
            psf__frontend_tsx.source as source__frontend_tsx
        FROM posthog_plugin
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
            message: pluginError.message,
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
}
