import { RedisPool } from '../../src/types'

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
