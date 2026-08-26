import { DeleteObjectCommand, PutObjectCommand, S3Client } from '@aws-sdk/client-s3'

import { ImageShardStore } from './image-shard-store'

describe('ImageShardStore', () => {
    const inlineImage = { pseudoTeam: '0'.repeat(32), hash: 'a'.repeat(22), bytes: Buffer.from('img') }
    const urlImage = {
        hash: 'AAAAAAAAAAAAAAAAAAAAAA',
        bytes: Buffer.from('scrubbed'),
        sourcePartition: 3,
        sourceOffset: 9,
    }

    it('aborts a shard write that exceeds the timeout so the flush throws and replays', async () => {
        const s3 = {
            send: (_cmd: unknown, opts: { abortSignal: AbortSignal }) =>
                new Promise((_resolve, reject) => {
                    opts.abortSignal.addEventListener('abort', () => reject(new Error('aborted')))
                }),
        } as unknown as S3Client
        const store = new ImageShardStore(s3, 'bucket', 'prefix', 5)

        await expect(store.writeShard([inlineImage])).rejects.toThrow()
    })

    it('deletes the orphaned shard when the index write fails', async () => {
        const deleted: string[] = []
        const s3 = {
            send: (command: PutObjectCommand | DeleteObjectCommand) => {
                if (command instanceof DeleteObjectCommand) {
                    deleted.push(command.input.Key ?? '')
                    return Promise.resolve()
                }
                return command.input.Key?.endsWith('.parquet')
                    ? Promise.reject(new Error('index write failed'))
                    : Promise.resolve()
            },
        } as unknown as S3Client
        const store = new ImageShardStore(s3, 'bucket', 'prefix', 5_000)

        await expect(store.writeShard([inlineImage])).rejects.toThrow('index write failed')
        expect(deleted).toHaveLength(1)
        expect(deleted[0]).toContain('/shards/')
    })

    it('creates a URL object once with its source position', async () => {
        const send = jest.fn().mockResolvedValueOnce({})
        const store = new ImageShardStore({ send } as unknown as S3Client, 'bucket', 'images', 1_000, 'node')

        await store.writeUrlImage(urlImage)

        const put = send.mock.calls[0][0] as PutObjectCommand
        expect(put.input).toMatchObject({
            Key: `images/url/${urlImage.hash}`,
            IfNoneMatch: '*',
            Metadata: { 'source-partition': '3', 'source-offset': '9' },
        })
    })

    it('keeps the first URL object when the key already exists', async () => {
        const exists = Object.assign(new Error('exists'), {
            name: 'PreconditionFailed',
            $metadata: { httpStatusCode: 412 },
        })
        const send = jest.fn().mockRejectedValueOnce(exists)
        const store = new ImageShardStore({ send } as unknown as S3Client, 'bucket', 'images', 1_000, 'node')

        await store.writeUrlImage(urlImage)

        expect(send).toHaveBeenCalledTimes(1)
        expect((send.mock.calls[0][0] as PutObjectCommand).input.IfNoneMatch).toBe('*')
    })

    it('retries a concurrent conditional create until one writer succeeds', async () => {
        const conflict = Object.assign(new Error('concurrent write'), {
            name: 'ConditionalRequestConflict',
            $metadata: { httpStatusCode: 409 },
        })
        const send = jest.fn().mockRejectedValueOnce(conflict).mockResolvedValueOnce({})
        const store = new ImageShardStore({ send } as unknown as S3Client, 'bucket', 'images', 1_000, 'node')

        await store.writeUrlImage(urlImage)

        expect(send).toHaveBeenCalledTimes(2)
        expect(send.mock.calls.map(([command]) => (command as PutObjectCommand).input.IfNoneMatch)).toEqual(['*', '*'])
    })
})
