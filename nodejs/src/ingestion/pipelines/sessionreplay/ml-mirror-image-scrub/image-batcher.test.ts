import { Message } from 'node-rdkafka'

import { hashImageBytes, imageRef } from './content-ref'
import { ImageBatcher, OffsetStore } from './image-batcher'
import { ImageShardStore, ScrubbedImage } from './image-shard-store'
import { ScrubClient } from './scrub-client'

const pt = (n: number): string => String(n).padStart(32, '0')
const CONTENT_KEY = 'fedcba9876543210fedcba9876543210'

function msg(partition: number, offset: number, pseudoTeam: string, bytes: Buffer, keyOverride?: string): Message {
    const ref = keyOverride ?? imageRef(pseudoTeam, hashImageBytes(CONTENT_KEY, bytes))
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

        expect(store.writes).toHaveLength(1)
        expect(store.writes[0].map((i) => i.pseudoTeam).sort()).toEqual([pt(1), pt(2)])
        expect(offsets.stored).toBe(1)
    })

    it('trusts the producer ref: the bytes are indexed under the key hash without recomputing it', async () => {
        // The hash is a producer-side per-team HMAC; this consumer has no key and must not try to
        // validate — it indexes the scrubbed bytes under whatever hash the ref carries.
        const store = new FakeStore()
        const batcher = new ImageBatcher(
            store as unknown as ImageShardStore,
            new FakeOffsets(),
            scrubClient,
            options,
            0
        )

        const ref = imageRef(pt(1), hashImageBytes('some-opaque-producer-key', Buffer.from('a')))
        await batcher.handleBatch([msg(0, 0, pt(1), Buffer.from('a'), ref)], 1)

        expect(store.writes).toHaveLength(1)
        expect(store.writes[0][0].hash).toBe(ref.split(':')[2])
    })

    it('does not store offsets when the shard write fails (at-least-once replay)', async () => {
        const store = new FakeStore()
        store.failNext = true
        const offsets = new FakeOffsets()
        const batcher = new ImageBatcher(store as unknown as ImageShardStore, offsets, scrubClient, options, 0)

        await expect(batcher.handleBatch([msg(0, 0, pt(1), Buffer.from('a'))], 1)).rejects.toThrow('s3 down')
        expect(offsets.stored).toBe(0)
    })

    it('flushes mid-batch when scrubbed bytes cross the byte bound instead of holding the whole batch', async () => {
        // Scrubbed outputs can be far larger than their inputs (full-resolution PNG re-encode), so
        // the byte bound must apply while a poll batch is still scrubbing — a reverted batcher that
        // accumulates all outputs first can hold gigabytes before its first flush.
        const store = new FakeStore()
        const offsets = new FakeOffsets()
        const bigOutputClient = { scrub: () => Promise.resolve(Buffer.alloc(16)) } as unknown as ScrubClient
        const batcher = new ImageBatcher(
            store as unknown as ImageShardStore,
            offsets,
            bigOutputClient,
            { ...options, maxBytes: 32, scrubConcurrency: 2 },
            0
        )

        const messages = Array.from({ length: 6 }, (_, i) => msg(0, i, pt(1), Buffer.from(`img-${i}`)))
        await batcher.handleBatch(messages, 1)

        expect(store.writes.length).toBeGreaterThan(1)
        expect(store.writes.flat()).toHaveLength(6)
        expect(offsets.stored).toBe(1)
    })

    it('does not count mid-batch flush time against the scrub deadline', async () => {
        // Slow-but-succeeding S3 writes must not exhaust the scrub budget: a reverted deadline that
        // spans flushes turns degraded storage into an abort/replay loop blamed on the sidecar.
        const slowStore = new FakeStore()
        const writeShard = slowStore.writeShard.bind(slowStore)
        slowStore.writeShard = async (images) => {
            await new Promise((resolve) => setTimeout(resolve, 80))
            return writeShard(images)
        }
        const offsets = new FakeOffsets()
        const batcher = new ImageBatcher(
            slowStore as unknown as ImageShardStore,
            offsets,
            { scrub: () => Promise.resolve(Buffer.alloc(16)) } as unknown as ScrubClient,
            { ...options, maxBytes: 32, scrubConcurrency: 2, maxBatchScrubMs: 60 },
            0
        )

        const messages = Array.from({ length: 6 }, (_, i) => msg(0, i, pt(1), Buffer.from(`img-${i}`)))
        await batcher.handleBatch(messages, 1)

        expect(slowStore.writes.flat()).toHaveLength(6)
        expect(offsets.stored).toBe(1)
    })

    test.each([[0], [NaN], [-1]])('rejects scrubConcurrency %p at construction', (scrubConcurrency) => {
        // 0 spins the chunk loop forever; NaN skips it entirely yet still commits offsets,
        // silently dropping the whole batch — both must fail loudly at boot instead.
        expect(
            () =>
                new ImageBatcher(
                    new FakeStore() as unknown as ImageShardStore,
                    new FakeOffsets(),
                    scrubClient,
                    { ...options, scrubConcurrency },
                    0
                )
        ).toThrow('scrubConcurrency')
    })

    it('aborts the batch and replays when scrubbing exceeds the deadline', async () => {
        const store = new FakeStore()
        const offsets = new FakeOffsets()
        const hangingClient = { scrub: () => new Promise<Buffer>(() => {}) } as unknown as ScrubClient
        const batcher = new ImageBatcher(
            store as unknown as ImageShardStore,
            offsets,
            hangingClient,
            { ...options, maxBatchScrubMs: 5 },
            0
        )

        await expect(batcher.handleBatch([msg(0, 0, pt(1), Buffer.from('a'))], 1)).rejects.toThrow()
        expect(offsets.stored).toBe(0)
        expect(store.writes).toHaveLength(0)
    })
})
