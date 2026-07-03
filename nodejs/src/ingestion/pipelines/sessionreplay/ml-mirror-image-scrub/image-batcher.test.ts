import { Message } from 'node-rdkafka'

import { hashImageBytes, imageRef } from './content-ref'
import { ImageBatcher, OffsetStore } from './image-batcher'
import { ImageShardStore, ScrubbedImage } from './image-shard-store'
import { ScrubClient } from './scrub-client'

// A fake 32-hex team pseudonym (real ones come from pseudonymize(); the consumer just treats it as opaque).
const pt = (n: number): string => String(n).padStart(32, '0')

function msg(partition: number, offset: number, pseudoTeam: string, bytes: Buffer, keyOverride?: string): Message {
    const ref = keyOverride ?? imageRef(pseudoTeam, hashImageBytes(bytes))
    return {
        topic: 'session_replay_image_scrub',
        partition,
        offset,
        key: Buffer.from(ref),
        value: bytes,
    } as unknown as Message
}

class FakeStore {
    public writes: ScrubbedImage[][] = []
    public failNext = false
    // eslint-disable-next-line @typescript-eslint/require-await
    async writeShard(images: ScrubbedImage[]): Promise<{ shard: string; bytes: number }> {
        if (this.failNext) {
            throw new Error('s3 down')
        }
        this.writes.push(images)
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
const options = {
    flushIntervalMs: 0,
    maxImages: 1000,
    maxBytes: 1e9,
    scrubConcurrency: 4,
    maxBatchScrubMs: 30_000,
}

describe('ImageBatcher', () => {
    it('scrubs a multi-team batch into one shard for the flush, storing offsets after', async () => {
        const store = new FakeStore()
        const offsets = new FakeOffsets()
        const batcher = new ImageBatcher(store as unknown as ImageShardStore, offsets, scrubClient, options, 0)

        await batcher.handleBatch([msg(0, 0, pt(1), Buffer.from('a')), msg(0, 1, pt(2), Buffer.from('b'))], 1)

        expect(store.writes).toHaveLength(1) // one shard for the whole flush, not one per team
        expect(store.writes[0].map((i) => i.pseudoTeam).sort()).toEqual([pt(1), pt(2)])
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
        const forged = imageRef(pt(1), hashImageBytes(Buffer.from('other')))
        await batcher.handleBatch([msg(0, 0, pt(1), Buffer.from('a'), forged)], 1)

        expect(store.writes).toHaveLength(0)
    })

    it('does not store offsets when the shard write fails (at-least-once replay)', async () => {
        const store = new FakeStore()
        store.failNext = true
        const offsets = new FakeOffsets()
        const batcher = new ImageBatcher(store as unknown as ImageShardStore, offsets, scrubClient, options, 0)

        await expect(batcher.handleBatch([msg(0, 0, pt(1), Buffer.from('a'))], 1)).rejects.toThrow('s3 down')
        expect(offsets.stored).toBe(0) // uncommitted → the window replays
    })

    it('aborts the batch and replays when scrubbing exceeds the deadline', async () => {
        const store = new FakeStore()
        const offsets = new FakeOffsets()
        // A sidecar that never answers: without a deadline handleBatch would hang the poll loop forever.
        const hangingClient = { scrub: () => new Promise<Buffer>(() => {}) } as unknown as ScrubClient
        const batcher = new ImageBatcher(
            store as unknown as ImageShardStore,
            offsets,
            hangingClient,
            { ...options, maxBatchScrubMs: 5 },
            0
        )

        await expect(batcher.handleBatch([msg(0, 0, pt(1), Buffer.from('a'))], 1)).rejects.toThrow()
        expect(offsets.stored).toBe(0) // uncommitted → the window replays instead of livelocking
        expect(store.writes).toHaveLength(0)
    })
})
