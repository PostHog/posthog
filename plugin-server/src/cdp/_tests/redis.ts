import { CdpRedis } from '../redis'

export async function deleteKeysWithPrefix(redis: CdpRedis, prefix: string) {
    await redis.useClient({ name: 'delete-keys' }, async (client) => {
        const keys = await client.keys(`${prefix}*`)
        const pipeline = client.pipeline()
        keys.forEach(function (key) {
            pipeline.del(key)
        })
        await pipeline.exec()
    })
}
