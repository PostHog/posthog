import { DeleteObjectCommand, HeadObjectCommand, PutObjectCommand, S3Client } from '@aws-sdk/client-s3'

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

    it('creates a missing URL object with a conditional fence and source position', async () => {
        const missing = Object.assign(new Error('missing'), { $metadata: { httpStatusCode: 404 } })
        const send = jest.fn().mockRejectedValueOnce(missing).mockResolvedValueOnce({})
        const store = new ImageShardStore({ send } as unknown as S3Client, 'bucket', 'images', 1_000, 'node')

        await store.writeUrlImage(urlImage)

        expect(send.mock.calls[0][0]).toBeInstanceOf(HeadObjectCommand)
        const put = send.mock.calls[1][0] as PutObjectCommand
        expect(put.input).toMatchObject({
            Key: `images/url/${urlImage.hash}`,
            IfNoneMatch: '*',
            Metadata: { 'source-partition': '3', 'source-offset': '9' },
        })
    })

    it('does not let an old owner overwrite a newer offset after a conditional conflict', async () => {
        const conflict = Object.assign(new Error('changed'), {
            name: 'PreconditionFailed',
            $metadata: { httpStatusCode: 412 },
        })
        const send = jest
            .fn()
            .mockResolvedValueOnce({
                ETag: '"old"',
                Metadata: { 'source-partition': '3', 'source-offset': '8' },
            })
            .mockRejectedValueOnce(conflict)
            .mockResolvedValueOnce({
                ETag: '"new"',
                Metadata: { 'source-partition': '3', 'source-offset': '10' },
            })
        const store = new ImageShardStore({ send } as unknown as S3Client, 'bucket', 'images', 1_000, 'node')

        await store.writeUrlImage(urlImage)

        const firstPut = send.mock.calls[1][0] as PutObjectCommand
        expect(firstPut.input.IfMatch).toBe('"old"')
        expect(send.mock.calls.map(([command]) => command.constructor)).toEqual([
            HeadObjectCommand,
            PutObjectCommand,
            HeadObjectCommand,
        ])
    })
})
