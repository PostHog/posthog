import { RedisV2 } from '~/common/redis/redis-v2'

export async function deleteKeysWithPrefix(redis: RedisV2, prefix: string) {
    await redis.useClient({ name: 'delete-keys' }, async (client) => {
        const keys = await client.keys(`${prefix}*`)
        const pipeline = client.pipeline()
        keys.forEach(function (key) {
            pipeline.del(key)
        })
        await pipeline.exec()
    })
}
