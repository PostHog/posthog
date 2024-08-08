import { RedisPool } from '../../src/types'

export async function deleteKeysWithPrefix(redisPool: RedisPool, prefix: string) {
    await redisPool.withClient('deleteKeysWithPrefix', 30 * 1000, async (client) => {
        const keys = await client.keys(`${prefix}*`)
        const pipeline = client.pipeline()
        keys.forEach(function (key) {
            pipeline.del(key)
        })
        await pipeline.exec()
    })
}
