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
} from '../../types'
import { PostgresUse } from './postgres'
import { sanitizeJsonbValue } from './utils'

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
        posthog_pluginconfig.updated_at,
        posthog_pluginconfig.created_at,
        posthog_pluginconfig.error IS NOT NULL AS has_error
    `

    return `SELECT ${fields}
       FROM posthog_pluginconfig
       LEFT JOIN posthog_team ON posthog_team.id = posthog_pluginconfig.team_id
       LEFT JOIN posthog_organization ON posthog_organization.id = posthog_team.organization_id
       LEFT JOIN posthog_plugin ON posthog_plugin.id = posthog_pluginconfig.plugin_id
       WHERE (
           posthog_pluginconfig.enabled='t' AND posthog_organization.plugins_access_level > 0
       )`
}

export async function getPluginRows(hub: Hub): Promise<Plugin[]> {
    const { rows }: { rows: Plugin[] } = await hub.db.postgres.query(
        PostgresUse.COMMON_READ,
        // `posthog_plugin` columns have to be listed individually, as we want to exclude a few columns
        // and Postgres syntax unfortunately doesn't have a column exclusion feature. The excluded columns are:
        // - archive - this is a potentially large blob, only extracted in Django as a plugin server optimization
        // - latest_tag - not used in this service
        // - latest_tag_checked_at - not used in this service
        `SELECT
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
            posthog_plugin.public_jobs,
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
            ON (psf__site_ts.plugin_id = posthog_plugin.id AND psf__site_ts.filename = 'site.ts')
        WHERE posthog_plugin.id IN (${pluginConfigsInForceQuery('plugin_id')}
        GROUP BY posthog_pluginconfig.plugin_id)`,
        undefined,
        'getPluginRows'
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
    pluginConfig: PluginConfig,
    capabilities: PluginCapabilities
): Promise<void> {
    await hub.db.postgres.query(
        PostgresUse.COMMON_WRITE,
        'UPDATE posthog_plugin SET capabilities = ($1) WHERE id = $2',
        [capabilities, pluginConfig.plugin_id],
        'setPluginCapabilities'
    )
}

export async function setError(hub: Hub, pluginError: PluginError | null, pluginConfig: PluginConfig): Promise<void> {
    await hub.db.postgres.query(
        PostgresUse.COMMON_WRITE,
        'UPDATE posthog_pluginconfig SET error = $1 WHERE id = $2',
        // NOTE: In theory `onEvent` shouldn't be seeing events that still have the null byte, but
        // it's better to be safe than sorry and sanitize the value here as well.
        [sanitizeJsonbValue(pluginError), typeof pluginConfig === 'object' ? pluginConfig?.id : pluginConfig],
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
    await hub.db.postgres.query(
        PostgresUse.COMMON_WRITE,
        `UPDATE posthog_pluginconfig SET enabled='f' WHERE id=$1 AND enabled='t'`,
        [pluginConfigId],
        'disablePlugin'
    )
    await hub.db.redisPublish(hub.PLUGINS_RELOAD_PUBSUB_CHANNEL, 'reload!')
}
