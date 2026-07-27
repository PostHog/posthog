import { DeleteObjectCommand, PutObjectCommand, S3Client } from '@aws-sdk/client-s3'

import { ImageShardStore } from './image-shard-store'

const image = { pseudoTeam: '0'.repeat(32), hash: 'a'.repeat(22), bytes: Buffer.from('img') }

describe('ImageShardStore', () => {
    it('aborts a shard write that exceeds the timeout so the flush throws and replays', async () => {
        const s3 = {
            send: (_cmd: unknown, opts: { abortSignal: AbortSignal }) =>
                new Promise((_resolve, reject) => {
                    opts.abortSignal.addEventListener('abort', () => reject(new Error('aborted')))
                }),
        } as unknown as S3Client
        const store = new ImageShardStore(s3, 'bucket', 'prefix', 5)

        await expect(store.writeShard([image])).rejects.toThrow()
    })

    it('deletes the orphaned shard when the index write fails', async () => {
        const deleted: string[] = []
        const s3 = {
            send: (cmd: PutObjectCommand | DeleteObjectCommand) => {
                if (cmd instanceof DeleteObjectCommand) {
                    deleted.push(cmd.input.Key ?? '')
                    return Promise.resolve()
                }
                return cmd.input.Key?.endsWith('.parquet')
                    ? Promise.reject(new Error('index write failed'))
                    : Promise.resolve() // shard PUT succeeds
            },
        } as unknown as S3Client
        const store = new ImageShardStore(s3, 'bucket', 'prefix', 5000)

        await expect(store.writeShard([image])).rejects.toThrow('index write failed')
        expect(deleted).toHaveLength(1)
        expect(deleted[0]).toContain('/shards/')
    })
})
