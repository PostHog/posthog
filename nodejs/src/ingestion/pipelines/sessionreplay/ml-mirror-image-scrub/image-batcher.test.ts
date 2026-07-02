import { Message } from 'node-rdkafka'

import { hashImageBytes, imageRef } from './content-ref'
import { ImageBatcher, OffsetStore } from './image-batcher'
import { ImageShardStore, ScrubbedImage } from './image-shard-store'
import { ScrubClient } from './scrub-client'

function msg(partition: number, offset: number, team: number, bytes: Buffer, keyOverride?: string): Message {
    const ref = keyOverride ?? imageRef(team, hashImageBytes(bytes))
    return {
        topic: 'session_replay_image_scrub',
        partition,
        offset,
        key: Buffer.from(ref),
        value: bytes,
    } as unknown as Message
}

class FakeStore {
    public writes: { teamId: number; images: ScrubbedImage[] }[] = []
    public failNext = false
    // eslint-disable-next-line @typescript-eslint/require-await
    async writeTeam(teamId: number, images: ScrubbedImage[]): Promise<{ shard: string; bytes: number }> {
        if (this.failNext) {
            throw new Error('s3 down')
        }
        this.writes.push({ teamId, images })
        return { shard: 'shard', bytes: images.reduce((n, i) => n + i.bytes.length, 0) }
    }
}

class FakeOffsets implements OffsetStore {
    public stored = 0
    offsetsStore(): void {
        this.stored += 1
    }
}

// Prefixes the bytes so the output differs from the input (like a real scrub would).
const scrubClient = {
    scrub: (b: Buffer) => Promise.resolve(Buffer.concat([Buffer.from('x'), b])),
} as unknown as ScrubClient
const options = { flushIntervalMs: 0, maxImages: 1000, maxBytes: 1e9, scrubConcurrency: 4 }

describe('ImageBatcher', () => {
    it('scrubs a batch, writes one shard per team, and stores offsets after the flush', async () => {
        const store = new FakeStore()
        const offsets = new FakeOffsets()
        const batcher = new ImageBatcher(store as unknown as ImageShardStore, offsets, scrubClient, options, 0)

        await batcher.handleBatch([msg(0, 0, 1, Buffer.from('a')), msg(0, 1, 2, Buffer.from('b'))], 1)

        expect(store.writes.map((w) => w.teamId).sort()).toEqual([1, 2]) // one shard per team
        expect(offsets.stored).toBe(1) // committed only after the write landed
    })

    it('drops a key/content mismatch without buffering it', async () => {
        const store = new FakeStore()
        const batcher = new ImageBatcher(
            store as unknown as ImageShardStore,
            new FakeOffsets(),
            scrubClient,
            options,
            0
        )

        // key claims a hash that doesn't match the value bytes
        const forged = imageRef(1, hashImageBytes(Buffer.from('other')))
        await batcher.handleBatch([msg(0, 0, 1, Buffer.from('a'), forged)], 1)

        expect(store.writes).toHaveLength(0)
    })

    it('does not store offsets when the shard write fails (at-least-once replay)', async () => {
        const store = new FakeStore()
        store.failNext = true
        const offsets = new FakeOffsets()
        const batcher = new ImageBatcher(store as unknown as ImageShardStore, offsets, scrubClient, options, 0)

        await expect(batcher.handleBatch([msg(0, 0, 1, Buffer.from('a'))], 1)).rejects.toThrow('s3 down')
        expect(offsets.stored).toBe(0) // uncommitted → the window replays
    })
})
