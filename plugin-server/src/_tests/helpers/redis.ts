import { CdpRedis } from '../../cdp/redis'
import { RedisPool } from '../../types'

export async function deleteKeysWithPrefix(redisPool: RedisPool, prefix: string) {
    const redisClient = await redisPool.acquire()
    const keys = await redisClient.keys(`${prefix}*`)
    const pipeline = redisClient.pipeline()
    keys.forEach(function (key) {
        pipeline.del(key)
    })
    await pipeline.exec()
    await redisPool.release(redisClient)
}

export async function deleteCDPKeysWithPrefix(redis: CdpRedis, prefix: string) {
    await redis.useClient({ name: 'delete-keys' }, async (client) => {
        const keys = await client.keys(`${prefix}*`)
        const pipeline = client.pipeline()
        keys.forEach(function (key) {
            pipeline.del(key)
        })
        await pipeline.exec()
    })
}
