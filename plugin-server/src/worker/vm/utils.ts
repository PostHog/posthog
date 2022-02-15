import { StatsD } from 'hot-shots'
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
    const incrementResult = await db.postgresQuery(
        `
        INSERT INTO posthog_pluginstorage (plugin_config_id, key, value)
        VALUES ($1, $2, $3)
        ON CONFLICT ("plugin_config_id", "key")
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
    const se = await db.postgresQuery(
        `
        INSERT INTO posthog_pluginstorage (plugin_config_id, key, value)
        VALUES ($1, $2, $3)
        ON CONFLICT ("plugin_config_id", "key")
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
        'SELECT * FROM posthog_pluginstorage WHERE "plugin_config_id"=$1 AND "key"=$2 LIMIT 1',
        [pluginConfigId, key],
        'storageGet'
    )
}

type BufferOptions = {
    limit: number
    timeoutSeconds: number
    onFlush: (objects: any[], points: number) => void | Promise<void>
}

export function createBuffer(opts: Partial<BufferOptions>, statsd?: StatsD) {
    const buffer = {
        _buffer: [] as any[],
        _timeout: null as NodeJS.Timeout | null,
        _lastFlushTriggered: new Date(),
        _points: 0,
        _options: {
            limit: 10,
            timeoutSeconds: 60,
            ...opts,
        } as BufferOptions,
        add: (object: any, points = 1) => {
            // flush existing if adding would make us go over the limit
            if (buffer._points && buffer._points + points > buffer._options.limit) {
                buffer.triggerFlushInstrumented()
            }

            // add the object to the buffer
            buffer._points += points
            buffer._buffer.push(object)

            if (buffer._points > buffer._options.limit) {
                // flush (again?) if we are now over the limit
                buffer.triggerFlushInstrumented()
            } else if (!buffer._timeout) {
                // if not, make sure there's a flush timeout
                buffer._timeout = setTimeout(
                    () => buffer.triggerFlushInstrumented(),
                    buffer._options.timeoutSeconds * 1000
                )
            }
        },
        triggerFlushInstrumented: () => {
            statsd?.increment(`buffer_voided_promises`)
            buffer._lastFlushTriggered = new Date()
            void buffer.flush()
        },
        flush: async (): Promise<void> => {
            if (buffer._timeout) {
                clearTimeout(buffer._timeout)
                buffer._timeout = null
            }
            if (buffer._buffer.length > 0 || buffer._points !== 0) {
                const oldBuffer = buffer._buffer
                const oldPoints = buffer._points
                buffer._buffer = []
                buffer._points = 0
                await buffer._options.onFlush?.(oldBuffer, oldPoints)
            }
            statsd?.timing(`buffer_promise_duration`, buffer._lastFlushTriggered)
        },
    }

    return buffer
}
