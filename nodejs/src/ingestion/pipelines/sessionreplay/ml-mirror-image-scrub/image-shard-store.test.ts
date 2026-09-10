import { DeleteObjectCommand, PutObjectCommand, S3Client } from '@aws-sdk/client-s3'
import { ParquetReader } from '@dsnp/parquetjs'

import { ImageShardStore } from './image-shard-store'

describe('ImageShardStore', () => {
    const inlineImage = { pseudoTeam: '0'.repeat(32), hash: 'a'.repeat(22), bytes: Buffer.from('img') }
    const urlImage = {
        hash: 'AAAAAAAAAAAAAAAAAAAAAA',
        bytes: Buffer.from('scrubbed'),
        sourcePartition: 3,
        sourceOffset: 9,
    }

    const s3Failure = (status?: number) =>
        Object.assign(
            new Error('s3 rejected the write'),
            status === undefined ? {} : { $metadata: { httpStatusCode: status } }
        )
    const noSleep = () => Promise.resolve()

    it.each([undefined, '42'])('writes the matching image index and prefers raw team ID %s', async (teamId) => {
        const send = jest.fn().mockResolvedValue({})
        const store = new ImageShardStore({ send } as unknown as S3Client, 'bucket', 'images', 1_000, 'node')
        await store.writeShard([{ ...inlineImage, teamId }])
        const prefix = teamId ? 'images/v2' : 'images'
        const shard = send.mock.calls[0][0] as PutObjectCommand
        const index = send.mock.calls[1][0] as PutObjectCommand
        expect(shard.input.Key).toMatch(new RegExp(`^${prefix}/shards/`))
        expect(index.input.Key).toMatch(new RegExp(`^${prefix}/index/`))
        const reader = await ParquetReader.openBuffer(index.input.Body as Buffer)
        try {
            const row = await reader.getCursor().next()
            expect(row).toMatchObject({
                format_version: BigInt(teamId ? 2 : 1),
                [teamId ? 'team_id' : 'pseudo_team']: teamId ?? inlineImage.pseudoTeam,
                shard: shard.input.Key,
                offset: BigInt(0),
                length: BigInt(inlineImage.bytes.length),
            })
            expect(row).not.toHaveProperty(teamId ? 'pseudo_team' : 'team_id')
        } finally {
            await reader.close()
        }
    })

    it('retries a shard write that exceeds the timeout, then gives up so the flush replays', async () => {
        const send = jest.fn(
            (_cmd: unknown, opts: { abortSignal: AbortSignal }) =>
                new Promise((_resolve, reject) => {
                    opts.abortSignal.addEventListener('abort', () => reject(new Error('aborted')))
                })
        )
        const store = new ImageShardStore({ send } as unknown as S3Client, 'bucket', 'prefix', 5, 'node', noSleep)

        await expect(store.writeShard([inlineImage])).rejects.toThrow('aborted')

        expect(send).toHaveBeenCalledTimes(3)
    })

    it.each([[500], [502], [503], [429], [undefined]])(
        'retries a shard write rejected with status %s, so one bad response does not restart the consumer',
        async (status) => {
            const send = jest.fn().mockRejectedValueOnce(s3Failure(status)).mockResolvedValue({})
            const store = new ImageShardStore(
                { send } as unknown as S3Client,
                'bucket',
                'prefix',
                1_000,
                'node',
                noSleep
            )

            await expect(store.writeShard([inlineImage])).resolves.toMatchObject({ bytes: 3 })

            expect(send).toHaveBeenCalledTimes(3)
        }
    )

    it.each([[400], [403], [404]])(
        'fails a shard write rejected with status %s without retrying, so a refusal does not spend the poll budget',
        async (status) => {
            const send = jest.fn().mockRejectedValue(s3Failure(status))
            const store = new ImageShardStore(
                { send } as unknown as S3Client,
                'bucket',
                'prefix',
                1_000,
                'node',
                noSleep
            )

            await expect(store.writeShard([inlineImage])).rejects.toThrow('s3 rejected the write')

            expect(send).toHaveBeenCalledTimes(1)
        }
    )

    it('deletes the orphaned shard when the index write fails', async () => {
        const deleted: string[] = []
        const s3 = {
            send: (command: PutObjectCommand | DeleteObjectCommand) => {
                if (command instanceof DeleteObjectCommand) {
                    deleted.push(command.input.Key ?? '')
                    return Promise.resolve()
                }
                return command.input.Key?.endsWith('.parquet')
                    ? Promise.reject(
                          Object.assign(new Error('index write failed'), { $metadata: { httpStatusCode: 403 } })
                      )
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

        await expect(store.writeUrlImage(urlImage)).resolves.toBe('created')

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

        await expect(store.writeUrlImage(urlImage)).resolves.toBe('already_exists')

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

        await expect(store.writeUrlImage(urlImage)).resolves.toBe('created')

        expect(send).toHaveBeenCalledTimes(2)
        expect(send.mock.calls.map(([command]) => (command as PutObjectCommand).input.IfNoneMatch)).toEqual(['*', '*'])
    })
})
