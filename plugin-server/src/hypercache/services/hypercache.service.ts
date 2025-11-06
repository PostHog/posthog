import { GetObjectCommand } from '@aws-sdk/client-s3'

import { Hub, RedisPool } from '~/types'
import { createRedisPool } from '~/utils/db/redis'
import { ObjectStorage, getObjectStorage } from '~/utils/object_storage'

const _HYPER_CACHE_EMPTY_VALUE = '__missing__'
export type HypercacheKey = 'surveys.json'

export type HypercacheResponse = {
    cacheKey: string
    cacheResult: 'hit' | 'miss'
    cacheSource: 'redis' | 's3' | 'missing'
    error?: string
    data?: string | null
}

const validateToken = (token: unknown): token is string => {
    // Check it is a token of limited chars
    return !!token && typeof token === 'string' && /^[a-zA-Z0-9_-]+$/.test(token)
}

export class HypercacheService {
    private redis: RedisPool
    private objectStorage: ObjectStorage
    public readonly redisCachePrefix = 'posthog:1:' // TODO: Make this configurable

    constructor(private hub: Hub) {
        // Setup redis client
        // NOTE: Make the redis pool configurable in the future
        this.redis = createRedisPool(this.hub, 'posthog')
        const objectStorage = getObjectStorage(this.hub)
        if (!objectStorage) {
            throw new Error('Object storage not configured')
        }
        this.objectStorage = objectStorage
    }

    public getTokenCacheKey(key: HypercacheKey, token: string): string {
        return `cache/team_tokens/${token}/${key}`
    }

    public getRedisCacheKey(key: HypercacheKey, token: string): string {
        return this.redisCachePrefix + this.getTokenCacheKey(key, token)
    }

    async getResourceViaToken(key: HypercacheKey, token: unknown): Promise<HypercacheResponse> {
        if (!validateToken(token)) {
            return {
                cacheKey: `invalid`,
                cacheResult: 'miss',
                cacheSource: 'missing',
                error: 'Invalid token',
            }
        }

        const cacheKey = this.getTokenCacheKey(key, token)

        const redisResult = await this.redis.useClient({ name: 'hypercache' }, async (client) => {
            return await client.get(this.getRedisCacheKey(key, token))
        })

        if (redisResult === _HYPER_CACHE_EMPTY_VALUE) {
            return {
                cacheKey,
                cacheResult: 'hit',
                cacheSource: 'redis',
                data: null,
            }
        }

        if (redisResult !== null) {
            return {
                cacheKey,
                cacheResult: 'hit',
                cacheSource: 'redis',
                data: redisResult,
            }
        }

        const s3Response = await this.objectStorage.s3
            .send(
                new GetObjectCommand({
                    Bucket: this.hub.OBJECT_STORAGE_BUCKET,
                    Key: cacheKey,
                })
            )
            .catch(() => null)

        if (s3Response && s3Response.Body) {
            const s3String = await s3Response.Body.transformToString().catch(() => null)

            if (s3String === _HYPER_CACHE_EMPTY_VALUE) {
                return {
                    cacheKey,
                    cacheResult: 'hit',
                    cacheSource: 'redis',
                    data: null,
                }
            }
            return {
                cacheKey,
                cacheResult: 'hit',
                cacheSource: 's3',
                data: s3String,
            }
        }

        return { cacheKey, cacheResult: 'miss', cacheSource: 'missing', data: null }
    }
}

// cache_key = self.get_cache_key(key)
// data = cache.get(cache_key)

// if data:
//     HYPERCACHE_CACHE_COUNTER.labels(result="hit_redis", namespace=self.namespace, value=self.value).inc()

//     if data == _HYPER_CACHE_EMPTY_VALUE:
//         return None, "redis"
//     else:
//         return json.loads(data), "redis"

// # Fallback to s3
// try:
//     data = object_storage.read(cache_key)
//     if data:
//         response = json.loads(data)
//         HYPERCACHE_CACHE_COUNTER.labels(result="hit_s3", namespace=self.namespace, value=self.value).inc()
//         self._set_cache_value_redis(key, response)
//         return response, "s3"
// except ObjectStorageError:
//     pass

// # NOTE: This only applies to the django version - the dedicated service will rely entirely on the cache
// data = self.load_fn(key)

// if isinstance(data, HyperCacheStoreMissing):
//     self._set_cache_value_redis(key, None)
//     HYPERCACHE_CACHE_COUNTER.labels(result="missing", namespace=self.namespace, value=self.value).inc()
//     return None, "db"

// self._set_cache_value_redis(key, data)
// HYPERCACHE_CACHE_COUNTER.labels(result="hit_db", namespace=self.namespace, value=self.value).inc()
// return data, "db"
