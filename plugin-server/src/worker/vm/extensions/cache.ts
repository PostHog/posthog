import { CacheExtension } from '@posthog/plugin-scaffold'

import { Hub } from '../../../types'
import { IllegalOperationError } from '../../../utils/utils'

export function getCacheKey(pluginId: number, teamId: number, key: string): string {
    return `@plugin/${pluginId}/${typeof teamId === 'undefined' ? '@all' : teamId}/${key}`
}

export function createCache(server: Hub, pluginId: number, teamId: number): CacheExtension {
    const getKey = (key: string) => getCacheKey(pluginId, teamId, key)
    return {
        set: async function (key, value, ttlSeconds, options) {
            return await server.db.redisSet(getKey(key), value, 'app_cache.set', ttlSeconds, options)
        },
        get: async function (key, defaultValue, options) {
            return await server.db.redisGet(getKey(key), defaultValue, 'app_cache.get', options)
        },
        incr: async function (key) {
            return await server.db.redisIncr(getKey(key))
        },
        expire: async function (key, ttlSeconds) {
            return await server.db.redisExpire(getKey(key), ttlSeconds)
        },
        lpush: async function (key, elementOrArray) {
            const isString = typeof elementOrArray === 'string'
            if (!Array.isArray(elementOrArray) && !isString) {
                throw new Error('cache.lpush expects a string value or an array of strings')
            }
            if (!isString) {
                if (elementOrArray.length > 1000) {
                    throw new IllegalOperationError('Too many elements in array for cache.lpush. Maximum: 1000')
                }
                elementOrArray = elementOrArray.map((el) => String(el))
            }
            return await server.db.redisLPush(getKey(key), elementOrArray, { jsonSerialize: false })
        },
        lrange: async function (key, startIndex, endIndex) {
            if (typeof startIndex !== 'number' || typeof endIndex !== 'number') {
                throw new Error('cache.lrange expects a number for the start and end indexes')
            }
            return await server.db.redisLRange(getKey(key), startIndex, endIndex)
        },
        llen: async function (key) {
            return await server.db.redisLLen(getKey(key))
        },
        lrem: async function (key, count, elementKey) {
            if (typeof count !== 'number') {
                throw new Error('cache.lrem expects a number for the "count" argument')
            }
            return await server.db.redisLRem(getKey(key), count, elementKey)
        },
        lpop: async function (key, count) {
            if (typeof count !== 'number') {
                throw new Error('cache.lpop expects a number for the "count" argument')
            }
            return await server.db.redisLPop(getKey(key), count)
        },
    }
}
