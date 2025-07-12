import { Counter, Summary } from 'prom-client'

import { StorageExtension } from '@posthog/plugin-scaffold'

import { Hub, PluginConfig } from '../../../types'
import { PostgresUse } from '../../../utils/db/postgres'
import { parseJSON } from '../../../utils/json-parse'
import { postgresGet } from '../utils'

const vmExtensionStorageGetCounter = new Counter({
    name: 'vm_extension_storage_get_total',
    help: 'Count of times vm extension storage get was called',
    labelNames: ['plugin_id'],
})
const vmExtensionStorageSetMsSummary = new Summary({
    name: 'vm_extension_storage_set_ms',
    help: 'Time to set storage value',
    labelNames: ['plugin_id'],
    percentiles: [0.5, 0.9, 0.95, 0.99],
})

export function createStorage(server: Hub, pluginConfig: PluginConfig): StorageExtension {
    const get = async function (key: string, defaultValue: unknown): Promise<unknown> {
        vmExtensionStorageGetCounter.labels(String(pluginConfig.plugin?.id)).inc()

        const result = await postgresGet(server.db, pluginConfig.id, key)
        return result?.rows.length === 1 ? parseJSON(result.rows[0].value) : defaultValue
    }
    const set = async function (key: string, value: unknown): Promise<void> {
        const timer = new Date()
        if (typeof value === 'undefined') {
            await del(key)
        } else {
            await server.db.postgres.query(
                PostgresUse.PLUGIN_STORAGE_RW,
                `
                    INSERT INTO posthog_pluginstorage ("plugin_config_id", "key", "value")
                    VALUES ($1, $2, $3)
                    ON CONFLICT ("plugin_config_id", "key")
                    DO UPDATE SET value = $3
                `,
                [pluginConfig.id, key, JSON.stringify(value)],
                `storageSet`
            )
        }

        vmExtensionStorageSetMsSummary
            .labels(String(pluginConfig.plugin?.id))
            .observe(new Date().getTime() - timer.getTime())
    }

    const del = async function (key: string): Promise<void> {
        await server.db.postgres.query(
            PostgresUse.PLUGIN_STORAGE_RW,
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
