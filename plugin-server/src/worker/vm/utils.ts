import { QueryResult } from 'pg'

import { PluginConfig } from '../../types'
import { DB } from '../../utils/db/db'

// This assumes the value stored at `key` can be cast to a Postgres numeric type
export const postgresIncrement = async (
    db: DB,
    pluginConfigId: PluginConfig['id'],
    key: string,
    incrementBy = 1
): Promise<number> => {
    // The timestamp is key to triggering the ON CONFLICT CLAUSE
    const incrementResult = await db.postgresQuery(
        `
        INSERT INTO posthog_pluginstorage (plugin_config_id, key, value, timestamp)
        VALUES ($1, $2, $3, to_timestamp(100000000000))
        ON CONFLICT ("plugin_config_id", "key", "timestamp")
        DO UPDATE SET value = posthog_pluginstorage.value::numeric + ${incrementBy}
        RETURNING value
        `,
        [pluginConfigId, key, incrementBy],
        'postgresIncrement'
    )

    return incrementResult.rows[0].value
}

export const postgresSetOnce = async (
    db: DB,
    pluginConfigId: PluginConfig['id'],
    key: string,
    value: number
): Promise<void> => {
    // The timestamp is key to triggering the ON CONFLICT CLAUSE
    await db.postgresQuery(
        `
        INSERT INTO posthog_pluginstorage (plugin_config_id, key, value, timestamp)
        VALUES ($1, $2, $3, to_timestamp(100000000000))
        ON CONFLICT ("plugin_config_id", "key", "timestamp")
        DO NOTHING
         `,
        [pluginConfigId, key, value],
        'postgresSetOnce'
    )
}

export const postgresGet = async (
    db: DB,
    pluginConfigId: PluginConfig['id'],
    key: string
): Promise<QueryResult<any>> => {
    return await db.postgresQuery(
        `SELECT value FROM posthog_pluginstorage 
        WHERE plugin_config_id = $1 AND key = $2
        ORDER BY timestamp DESC
        LIMIT 1`,
        [pluginConfigId, key],
        'storageGet'
    )
}
