import { StorageExtension } from '@posthog/plugin-scaffold'

import { Hub, PluginConfig } from '../../../types'
import { postgresGet } from './../utils'

export function createStorage(server: Hub, pluginConfig: PluginConfig): StorageExtension {
    const get = async function (key: string, defaultValue: unknown): Promise<unknown> {
        server.statsd?.increment('vm_extension_storage_get', {
            plugin: pluginConfig.plugin?.name ?? '?',
            team_id: pluginConfig.team_id.toString(),
        })

        const result = await postgresGet(server.db, pluginConfig.id, key)
        return result?.rows.length === 1 ? JSON.parse(result.rows[0].value) : defaultValue
    }
    const set = async function (key: string, value: unknown): Promise<void> {
        const timer = new Date()
        if (typeof value === 'undefined') {
            await del(key)
        } else {
            // conflicts can in theory happen if key && plugin_config_id && timestamp match
            // it's highly unlikely that timestamps will match but in that case it's fine for us to pick either value
            await server.db.postgresQuery(
                `
                    INSERT INTO posthog_pluginstorage ("plugin_config_id", "key", "value", "timestamp")
                    VALUES ($1, $2, $3, now())
                    ON CONFLICT ("plugin_config_id", "key", "timestamp")
                    DO NOTHING
                `,
                [pluginConfig.id, key, JSON.stringify(value)],
                'storageSet'
            )
        }

        server.statsd?.increment('vm_extension_storage_set', {
            plugin: pluginConfig.plugin?.name ?? '?',
            team_id: pluginConfig.team_id.toString(),
        })
        server.statsd?.timing('vm_extension_storage_set_timing', timer, {
            plugin: pluginConfig.plugin?.name ?? '?',
            team_id: pluginConfig.team_id.toString(),
        })
    }

    const del = async function (key: string): Promise<void> {
        await server.db.postgresQuery(
            'DELETE FROM posthog_pluginstorage WHERE "plugin_config_id"=$1 AND "key"=$2',
            [pluginConfig.id, key],
            'storageDelete'
        )
    }

    return {
        get,
        set,
        del,
    }
}
