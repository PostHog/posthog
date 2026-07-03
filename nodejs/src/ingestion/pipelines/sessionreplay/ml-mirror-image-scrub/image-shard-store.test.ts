import { S3Client } from '@aws-sdk/client-s3'

import { ImageShardStore } from './image-shard-store'

describe('ImageShardStore', () => {
    it('aborts a shard write that exceeds the timeout so the flush throws and replays', async () => {
        // A send that never resolves on its own: without the timeout, writeShard would hang the poll loop forever.
        const s3 = {
            send: (_cmd: unknown, opts: { abortSignal: AbortSignal }) =>
                new Promise((_resolve, reject) => {
                    opts.abortSignal.addEventListener('abort', () => reject(new Error('aborted')))
                }),
        } as unknown as S3Client
        const store = new ImageShardStore(s3, 'bucket', 'prefix', 5)

        await expect(
            store.writeShard([{ pseudoTeam: '0'.repeat(32), hash: 'a'.repeat(22), bytes: Buffer.from('img') }])
        ).rejects.toThrow()
    })
})
