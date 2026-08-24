import { Message, MessageHeader, TopicPartitionOffset } from 'node-rdkafka'
import { gzipSync } from 'node:zlib'

import { hashImageBytes, imageRef, urlRef } from './content-ref'
import { ImageBatcher, OffsetStore } from './image-batcher'
import { ImageShardStore, ScrubbedImage, ScrubbedUrlImage } from './image-shard-store'
import { ImageScrubConsumerMetrics } from './metrics'
import { ScrubClient, ScrubPoisoned } from './scrub-client'

const pt = (n: number): string => String(n).padStart(32, '0')
const CONTENT_KEY = 'fedcba9876543210fedcba9876543210'

function msg(
    partition: number,
    offset: number,
    pseudoTeam: string,
    bytes: Buffer,
    keyOverride?: string,
    headers?: MessageHeader[]
): Message {
    const ref = keyOverride ?? imageRef(pseudoTeam, hashImageBytes(CONTENT_KEY, bytes))
    return {
        topic: 'session_replay_image_scrub',
        partition,
        offset,
        key: Buffer.from(ref),
        value: bytes,
        headers,
    } as unknown as Message
}

class FakeStore {
    public writes: ScrubbedImage[][] = []
    public urlWrites: ScrubbedUrlImage[] = []
    public failNext = false
    public failNextUrl = false
    // eslint-disable-next-line @typescript-eslint/require-await
    async writeShard(images: ScrubbedImage[]): Promise<{ shard: string; bytes: number }> {
        if (this.failNext) {
            throw new Error('s3 down')
        }
        this.writes.push(images)
        return { shard: 'shard', bytes: images.reduce((n, i) => n + i.bytes.length, 0) }
    }

    // eslint-disable-next-line @typescript-eslint/require-await
    async writeUrlImage(image: ScrubbedUrlImage): Promise<void> {
        if (this.failNextUrl) {
            throw new Error('url s3 down')
        }
        this.urlWrites.push(image)
    }
}

class FakeOffsets implements OffsetStore {
    public stored = 0
    public received: TopicPartitionOffset[][] = []
    offsetsStore(offsets: TopicPartitionOffset[]): void {
        this.stored += 1
        this.received.push(offsets)
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
    dedupMaxRefs: 1000,
}

describe('ImageBatcher', () => {
    afterEach(() => jest.restoreAllMocks())

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

    it('decodes and validates a URL image from its Kafka transport headers before scrubbing it', async () => {
        const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
        const received: Buffer[] = []
        const capturingClient = {
            scrub: (bytes: Buffer) => {
                received.push(bytes)
                return Promise.resolve(bytes)
            },
        } as unknown as ScrubClient
        const store = new FakeStore()
        const batcher = new ImageBatcher(
            store as unknown as ImageShardStore,
            new FakeOffsets(),
            capturingClient,
            options,
            0
        )
        const ref = urlRef(hashImageBytes(CONTENT_KEY, Buffer.from('https://example.com/image.png')))

        await batcher.handleBatch(
            [
                msg(0, 0, pt(1), gzipSync(png), ref, [
                    { 'content-type': Buffer.from('image/png') },
                    { 'content-encoding': Buffer.from('gzip') },
                ]),
            ],
            1
        )

        expect(received).toEqual([png])
        expect(store.urlWrites).toEqual([
            {
                hash: ref.slice('imageurl:'.length),
                bytes: png,
                sourcePartition: 0,
                sourceOffset: 0,
            },
        ])
        expect(store.writes).toHaveLength(0)
    })

    it('submits every valid URL image for the conditional store to select the first completed write', async () => {
        const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
        const newer = Buffer.concat([png, Buffer.from('newer')])
        const older = Buffer.concat([png, Buffer.from('older')])
        const store = new FakeStore()
        const batcher = new ImageBatcher(
            store as unknown as ImageShardStore,
            new FakeOffsets(),
            { scrub: (bytes: Buffer) => Promise.resolve(bytes) } as unknown as ScrubClient,
            options,
            0
        )
        const ref = urlRef(hashImageBytes(CONTENT_KEY, Buffer.from('https://example.com/image.png')))

        await batcher.handleBatch(
            [
                msg(0, 12, pt(1), newer, ref, [{ 'content-type': Buffer.from('image/png') }]),
                msg(0, 10, pt(1), older, ref, [{ 'content-type': Buffer.from('image/png') }]),
            ],
            1
        )

        expect(store.urlWrites).toEqual([
            {
                hash: ref.slice('imageurl:'.length),
                bytes: newer,
                sourcePartition: 0,
                sourceOffset: 12,
            },
            {
                hash: ref.slice('imageurl:'.length),
                bytes: older,
                sourcePartition: 0,
                sourceOffset: 10,
            },
        ])
    })

    it('uses a later valid URL image when an earlier candidate for the ref is invalid', async () => {
        const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
        const store = new FakeStore()
        const batcher = new ImageBatcher(
            store as unknown as ImageShardStore,
            new FakeOffsets(),
            { scrub: (bytes: Buffer) => Promise.resolve(bytes) } as unknown as ScrubClient,
            options,
            0
        )
        const ref = urlRef(hashImageBytes(CONTENT_KEY, Buffer.from('https://example.com/image.png')))

        await batcher.handleBatch(
            [
                msg(0, 10, pt(1), Buffer.from('not a png'), ref, [{ 'content-type': Buffer.from('image/png') }]),
                msg(0, 11, pt(1), png, ref, [{ 'content-type': Buffer.from('image/png') }]),
            ],
            1
        )

        expect(store.urlWrites).toEqual([
            {
                hash: ref.slice('imageurl:'.length),
                bytes: png,
                sourcePartition: 0,
                sourceOffset: 11,
            },
        ])
    })

    it('scrubs a newer URL version after an earlier version was persisted by the same pod', async () => {
        const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
        const first = Buffer.concat([png, Buffer.from('first')])
        const second = Buffer.concat([png, Buffer.from('second')])
        const store = new FakeStore()
        const batcher = new ImageBatcher(
            store as unknown as ImageShardStore,
            new FakeOffsets(),
            { scrub: (bytes: Buffer) => Promise.resolve(bytes) } as unknown as ScrubClient,
            options,
            0
        )
        const ref = urlRef(hashImageBytes(CONTENT_KEY, Buffer.from('https://example.com/image.png')))

        await batcher.handleBatch([msg(0, 10, pt(1), first, ref, [{ 'content-type': Buffer.from('image/png') }])], 1)
        await batcher.handleBatch([msg(0, 11, pt(1), second, ref, [{ 'content-type': Buffer.from('image/png') }])], 2)

        expect(store.urlWrites.map((image) => [image.sourceOffset, image.bytes])).toEqual([
            [10, first],
            [11, second],
        ])
    })

    it('bounds concurrent URL-image writes by the scrub worker limit', async () => {
        const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
        let activeWrites = 0
        let maximumActiveWrites = 0
        const store = {
            writeUrlImage: async () => {
                activeWrites += 1
                maximumActiveWrites = Math.max(maximumActiveWrites, activeWrites)
                await Promise.resolve()
                activeWrites -= 1
            },
            writeShard: () => Promise.resolve({ shard: 'unused', bytes: 0 }),
        } as unknown as ImageShardStore
        const batcher = new ImageBatcher(
            store,
            new FakeOffsets(),
            { scrub: () => Promise.resolve(png) } as unknown as ScrubClient,
            { ...options, scrubConcurrency: 2 },
            0
        )
        const messages = Array.from({ length: 6 }, (_, index) => {
            const ref = urlRef(hashImageBytes(CONTENT_KEY, Buffer.from(`https://example.com/${index}.png`)))
            return msg(0, index, pt(1), png, ref, [{ 'content-type': Buffer.from('image/png') }])
        })

        await batcher.handleBatch(messages, 1)

        expect(maximumActiveWrites).toBe(2)
    })

    it('drops a URL image whose bytes do not match its Kafka content-type', async () => {
        let scrubCalls = 0
        const batcher = new ImageBatcher(
            new FakeStore() as unknown as ImageShardStore,
            new FakeOffsets(),
            {
                scrub: () => {
                    scrubCalls += 1
                    return Promise.resolve(Buffer.from('scrubbed'))
                },
            } as unknown as ScrubClient,
            options,
            0
        )
        const ref = urlRef(hashImageBytes(CONTENT_KEY, Buffer.from('https://example.com/image.png')))

        await batcher.handleBatch(
            [msg(0, 0, pt(1), Buffer.from([0xff, 0xd8, 0xff]), ref, [{ 'content-type': Buffer.from('image/png') }])],
            1
        )

        expect(scrubCalls).toBe(0)
    })

    it('does not store offsets when the shard write fails (at-least-once replay)', async () => {
        const store = new FakeStore()
        store.failNext = true
        const offsets = new FakeOffsets()
        const batcher = new ImageBatcher(store as unknown as ImageShardStore, offsets, scrubClient, options, 0)

        await expect(batcher.handleBatch([msg(0, 0, pt(1), Buffer.from('a'))], 1)).rejects.toThrow('s3 down')
        expect(offsets.stored).toBe(0)
    })

    it('does not create a random inline shard before deterministic URL writes succeed', async () => {
        const store = new FakeStore()
        store.failNextUrl = true
        const offsets = new FakeOffsets()
        const batcher = new ImageBatcher(store as unknown as ImageShardStore, offsets, scrubClient, options, 0)
        const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
        const ref = urlRef(hashImageBytes(CONTENT_KEY, Buffer.from('https://example.com/image.png')))

        await expect(
            batcher.handleBatch(
                [
                    msg(0, 0, pt(1), Buffer.from('inline')),
                    msg(0, 1, pt(1), png, ref, [{ 'content-type': Buffer.from('image/png') }]),
                ],
                1
            )
        ).rejects.toThrow('url s3 down')

        expect(store.writes).toHaveLength(0)
        expect(offsets.stored).toBe(0)
    })

    it('stores offsets with each mid-batch flush, so a later failure replays only from the flush', async () => {
        // A flush persists a randomly named shard; if the batch then fails (e.g. the scrub deadline)
        // without having stored the flushed messages' offsets, Kafka replays them and every replay
        // writes another duplicate shard — unbounded write amplification an attacker can induce.
        const store = new FakeStore()
        const offsets = new FakeOffsets()
        let scrubs = 0
        const failsAfterFirstChunk = {
            scrub: () => {
                scrubs += 1
                return scrubs <= 2 ? Promise.resolve(Buffer.alloc(16)) : Promise.reject(new Error('sidecar down'))
            },
        } as unknown as ScrubClient
        const batcher = new ImageBatcher(
            store as unknown as ImageShardStore,
            offsets,
            failsAfterFirstChunk,
            { ...options, maxBytes: 32, scrubConcurrency: 2 },
            0
        )

        const messages = Array.from({ length: 4 }, (_, i) => msg(0, i, pt(1), Buffer.from(`img-${i}`)))
        await expect(batcher.handleBatch(messages, 1)).rejects.toThrow('sidecar down')

        expect(store.writes).toHaveLength(1)
        // The flushed chunk's messages (offsets 0-1) are recorded, so only 2-3 replay.
        expect(offsets.received).toEqual([[{ topic: 'session_replay_image_scrub', partition: 0, offset: 2 }]])
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
        expect(offsets.stored).toBe(store.writes.length)
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
            { ...options, maxBytes: 32, scrubConcurrency: 2 },
            0
        )

        const messages = Array.from({ length: 6 }, (_, i) => msg(0, i, pt(1), Buffer.from(`img-${i}`)))
        await batcher.handleBatch(messages, 1)

        expect(slowStore.writes.flat()).toHaveLength(6)
        expect(offsets.stored).toBe(slowStore.writes.length)
    })

    it('scrubs each ref once: duplicates in and across batches skip the sidecar but still advance offsets', async () => {
        // The topic is keyed by ref, so duplicate produces (per-mirror-pod producer dedup misses
        // cross-pod repeats) are partition-affine; losing this dedup silently re-burns sidecar CPU
        // per duplicate and writes duplicate shard entries.
        const store = new FakeStore()
        const offsets = new FakeOffsets()
        let scrubs = 0
        const countingClient = {
            scrub: (b: Buffer) => {
                scrubs += 1
                return Promise.resolve(b)
            },
        } as unknown as ScrubClient
        const batcher = new ImageBatcher(store as unknown as ImageShardStore, offsets, countingClient, options, 0)

        const sprite = Buffer.from('sprite')
        await batcher.handleBatch([msg(0, 0, pt(1), sprite), msg(0, 1, pt(1), sprite)], 1)
        await batcher.handleBatch([msg(0, 2, pt(1), sprite)], 2)

        expect(scrubs).toBe(1)
        expect(store.writes.flat()).toHaveLength(1)
        // The all-duplicate second batch still advances offsets, or the duplicates replay forever.
        expect(offsets.received.at(-1)).toEqual([{ topic: 'session_replay_image_scrub', partition: 0, offset: 3 }])
    })

    it.each([0, 1000])(
        'scrubs the distinct images of a duplicate-heavy batch at full concurrency (dedupMaxRefs %p)',
        async (dedupMaxRefs) => {
            // Duplicates have to collapse before the batch is chunked. Left in, they occupy
            // concurrency slots, so a chunk finishes as soon as its one distinct image does and the
            // batch serializes behind the chunk barriers — the lane then runs one image in flight
            // instead of scrubConcurrency, regardless of how many pods it has. Consecutive repeats
            // are the realistic shape: one sprite recurs across a session's snapshots.
            const store = new FakeStore()
            let inFlight = 0
            let maxInFlight = 0
            let scrubs = 0
            const trackingClient = {
                scrub: async (b: Buffer) => {
                    scrubs += 1
                    inFlight += 1
                    maxInFlight = Math.max(maxInFlight, inFlight)
                    await new Promise((resolve) => setImmediate(resolve))
                    inFlight -= 1
                    return b
                },
            } as unknown as ScrubClient
            const batcher = new ImageBatcher(
                store as unknown as ImageShardStore,
                new FakeOffsets(),
                trackingClient,
                { ...options, dedupMaxRefs },
                0
            )

            const batch: Message[] = []
            for (let sprite = 0; sprite < 4; sprite++) {
                for (let repeat = 0; repeat < 8; repeat++) {
                    batch.push(msg(0, batch.length, pt(1), Buffer.from(`sprite-${sprite}`)))
                }
            }
            await batcher.handleBatch(batch, 1)

            expect(scrubs).toBe(4)
            expect(maxInFlight).toBe(4)
            expect(store.writes.flat()).toHaveLength(4)
        }
    )

    it('refills a slot as soon as it frees rather than waiting on the slowest image in flight', async () => {
        // Awaiting a whole group of scrubConcurrency before starting the next means one slow image
        // holds its group's other slots idle until it finishes, so throughput tracks the slowest image
        // in each group rather than the average one. On a spread-out scrub-time distribution that is
        // most of the sidecar's capacity. A sliding window costs one slot for a slow image, not all of
        // them, so every remaining image is already in flight before the slow one returns.
        const store = new FakeStore()
        let releaseSlow = (): void => {}
        const slow = new Promise<void>((resolve) => (releaseSlow = resolve))
        let started = 0
        const gatedClient = {
            scrub: (b: Buffer) => {
                started += 1
                return b.toString() === 'slow' ? slow.then(() => b) : Promise.resolve(b)
            },
        } as unknown as ScrubClient
        const batcher = new ImageBatcher(
            store as unknown as ImageShardStore,
            new FakeOffsets(),
            gatedClient,
            options,
            0
        )

        const batch: Message[] = [msg(0, 0, pt(1), Buffer.from('slow'))]
        for (let i = 1; i < 8; i++) {
            batch.push(msg(0, i, pt(1), Buffer.from(`img-${i}`)))
        }
        const running = batcher.handleBatch(batch, 1)
        for (let tick = 0; tick < 20; tick++) {
            await new Promise((resolve) => setImmediate(resolve))
        }

        // All 8 are in flight while the slow one is still blocked; a barrier would stall at 4.
        expect(started).toBe(8)

        releaseSlow()
        await running
        expect(store.writes.flat()).toHaveLength(8)
    })

    it('never writes an image whose offset a slow predecessor is still holding back', async () => {
        // Completions arrive out of order, so a slow first image leaves later ones finished but not
        // retired. Writing those on a capacity flush persists bytes whose offsets cannot be stored
        // yet, and a batch failure then rewrites them under a fresh shard key: the same content in
        // two shards, and two index rows pointing at it. A flush must only ever cover what it can
        // also commit.
        const store = new FakeStore()
        const offsets = new FakeOffsets()
        let releaseSlow = (): void => {}
        const slow = new Promise<void>((resolve) => (releaseSlow = resolve))
        const gatedClient = {
            scrub: (b: Buffer) => (b.toString() === 'slow' ? slow.then(() => b) : Promise.resolve(b)),
        } as unknown as ScrubClient
        const batcher = new ImageBatcher(
            store as unknown as ImageShardStore,
            offsets,
            gatedClient,
            { ...options, maxImages: 2, scrubConcurrency: 4 },
            0
        )

        const batch: Message[] = [msg(0, 0, pt(1), Buffer.from('slow'))]
        for (let i = 1; i < 5; i++) {
            batch.push(msg(0, i, pt(1), Buffer.from(`img-${i}`)))
        }
        const running = batcher.handleBatch(batch, 1)
        for (let tick = 0; tick < 20; tick++) {
            await new Promise((resolve) => setImmediate(resolve))
        }

        // The fast images are done but unretired, so nothing may be written or committed yet.
        expect(store.writes.flat()).toHaveLength(0)
        expect(offsets.received).toHaveLength(0)

        releaseSlow()
        await running

        expect(store.writes.flat()).toHaveLength(5)
        expect(offsets.received.at(-1)).toEqual([{ topic: 'session_replay_image_scrub', partition: 0, offset: 5 }])
    })

    it('rescrubs an image whose batch failed rather than pod-deduping the replay away', async () => {
        // A ref is marked seen only once its image is buffered. Marking it at plan time, or inside
        // scrubOne, reads as a harmless simplification and silently drops the image instead: the
        // replay is pod-deduped, its offset advances, and nothing ever writes it. No error, no
        // counter, and every other test still green.
        let attempts = 0
        const flakyClient = {
            scrub: (b: Buffer) => {
                attempts += 1
                return attempts === 1 ? Promise.reject(new Error('sidecar down')) : Promise.resolve(b)
            },
        } as unknown as ScrubClient
        const store = new FakeStore()
        const batcher = new ImageBatcher(
            store as unknown as ImageShardStore,
            new FakeOffsets(),
            flakyClient,
            options,
            0
        )
        const sprite = Buffer.from('sprite')

        await expect(batcher.handleBatch([msg(0, 0, pt(1), sprite)], 1)).rejects.toThrow('sidecar down')
        await batcher.handleBatch([msg(0, 0, pt(1), sprite)], 2)

        expect(store.writes.flat()).toHaveLength(1)
    })

    it('advances every partition past the duplicates it skipped, not just the one it scrubbed on', async () => {
        // The span walk is the one place that can commit an offset for a message it never processed,
        // and that failure is silent permanent loss. Both partitions here end on a duplicate, so the
        // trailing skips are only covered if the final recordOffsets spans the whole batch.
        const offsets = new FakeOffsets()
        const batcher = new ImageBatcher(
            new FakeStore() as unknown as ImageShardStore,
            offsets,
            scrubClient,
            options,
            0
        )
        const a = Buffer.from('a')
        const b = Buffer.from('b')

        await batcher.handleBatch(
            [msg(0, 100, pt(1), a), msg(1, 200, pt(1), b), msg(0, 101, pt(1), a), msg(1, 201, pt(1), b)],
            1
        )

        expect(offsets.received.at(-1)).toEqual(
            expect.arrayContaining([
                { topic: 'session_replay_image_scrub', partition: 0, offset: 102 },
                { topic: 'session_replay_image_scrub', partition: 1, offset: 202 },
            ])
        )
    })

    it('leaves both partitions replayable when a chunk fails after a mid-batch flush', async () => {
        // A mid-batch flush commits offsets for the prefix it persisted, and everything after it has
        // to stay replayable. Multi-partition is where that can quietly go wrong, because each
        // partition carries its own maximum and only one of them appears in a given chunk's span.
        const store = new FakeStore()
        const offsets = new FakeOffsets()
        let scrubs = 0
        const failLateClient = {
            scrub: (b: Buffer) => {
                scrubs += 1
                return scrubs > 2 ? Promise.reject(new Error('sidecar down')) : Promise.resolve(b)
            },
        } as unknown as ScrubClient
        const batcher = new ImageBatcher(
            store as unknown as ImageShardStore,
            offsets,
            failLateClient,
            { ...options, maxImages: 2, scrubConcurrency: 2 },
            0
        )

        await expect(
            batcher.handleBatch(
                [
                    msg(0, 10, pt(1), Buffer.from('a')),
                    msg(1, 20, pt(1), Buffer.from('b')),
                    msg(0, 11, pt(1), Buffer.from('c')),
                    msg(1, 21, pt(1), Buffer.from('d')),
                ],
                1
            )
        ).rejects.toThrow('sidecar down')

        expect(offsets.received).toHaveLength(1)
        expect(offsets.received[0]).toHaveLength(2)
        expect(offsets.received[0]).toEqual(
            expect.arrayContaining([
                { topic: 'session_replay_image_scrub', partition: 0, offset: 11 },
                { topic: 'session_replay_image_scrub', partition: 1, offset: 21 },
            ])
        )
    })

    it('stops re-sending an image the sidecar permanently rejected', async () => {
        // A 422/413 is a verdict on the content, so every later copy would earn the same rejection.
        // Without marking it, the most broken images are the ones that keep costing sidecar calls.
        let calls = 0
        const rejectingClient = {
            scrub: () => {
                calls += 1
                return Promise.resolve(null)
            },
        } as unknown as ScrubClient
        const batcher = new ImageBatcher(
            new FakeStore() as unknown as ImageShardStore,
            new FakeOffsets(),
            rejectingClient,
            options,
            0
        )
        const broken = Buffer.from('broken')

        await batcher.handleBatch([msg(0, 0, pt(1), broken)], 1)
        await batcher.handleBatch([msg(0, 1, pt(1), broken)], 2)

        expect(calls).toBe(1)
    })

    it('dedupMaxRefs 0 disables the cross-batch cache but never intra-batch dedup', async () => {
        const store = new FakeStore()
        const batcher = new ImageBatcher(
            store as unknown as ImageShardStore,
            new FakeOffsets(),
            scrubClient,
            { ...options, dedupMaxRefs: 0 },
            0
        )

        const sprite = Buffer.from('sprite')
        await batcher.handleBatch([msg(0, 0, pt(1), sprite)], 1)
        await batcher.handleBatch([msg(0, 1, pt(1), sprite)], 2)
        expect(store.writes.flat()).toHaveLength(2)

        // Intra-batch dedup keeps no state between batches, so turning the cache off cannot reach it.
        await batcher.handleBatch([msg(0, 2, pt(1), sprite), msg(0, 3, pt(1), sprite)], 3)
        expect(store.writes.flat()).toHaveLength(3)
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

    it('parks a poison image and lets the batch move past it', async () => {
        const store = new FakeStore()
        const offsets = new FakeOffsets()
        const parked: string[] = []
        const poisonClient = {
            scrub: (b: Buffer) =>
                b.toString() === 'poison'
                    ? Promise.reject(
                          new ScrubPoisoned('cannot process', {
                              reason: 'transport',
                              lastError: 'sidecar responded 500',
                              attempts: 12,
                              waitedMs: 60_000,
                          })
                      )
                    : Promise.resolve(b),
        } as unknown as ScrubClient
        const batcher = new ImageBatcher(store as unknown as ImageShardStore, offsets, poisonClient, options, 0, {
            park: (image) => Promise.resolve(void parked.push(image.ref)),
        })

        await batcher.handleBatch([msg(0, 0, pt(1), Buffer.from('poison')), msg(0, 1, pt(1), Buffer.from('ok'))], 1)

        expect(parked).toHaveLength(1)
        // The healthy image behind it still gets written, and the offset advances over both.
        expect(store.writes.flat()).toHaveLength(1)
        expect(offsets.received.flat().map((o) => o.offset)).toEqual([2])
    })

    it('preserves the replay count when re-parking, so round trips accumulate', async () => {
        // The cap that stops an image cycling between the two topics only binds if the count comes
        // back out with it. Dropped here, every replay run starts the image at zero and it can be
        // pushed at a sidecar that still cannot take it forever.
        const parked: Record<string, unknown>[] = []
        const poisonClient = {
            scrub: () =>
                Promise.reject(
                    new ScrubPoisoned('cannot process', {
                        reason: 'rejected',
                        lastError: 'sidecar responded 500',
                        attempts: 12,
                        waitedMs: 60_000,
                    })
                ),
        } as unknown as ScrubClient
        const batcher = new ImageBatcher(
            new FakeStore() as unknown as ImageShardStore,
            new FakeOffsets(),
            poisonClient,
            options,
            0,
            { park: (image) => Promise.resolve(void parked.push(image.detail)) }
        )

        const replayed = msg(0, 0, pt(1), Buffer.from('poison'))
        ;(replayed as unknown as { headers: unknown[] }).headers = [{ replayCount: Buffer.from('1') }]
        await batcher.handleBatch([replayed], 1)

        expect(parked[0].replayCount).toBe(1)
    })

    it('preserves URL transport headers when it parks the original compressed bytes', async () => {
        const parked: { headers: Record<string, string>; bytes: Buffer }[] = []
        const poisonClient = {
            scrub: () =>
                Promise.reject(
                    new ScrubPoisoned('cannot process', {
                        reason: 'rejected',
                        lastError: 'sidecar responded 500',
                        attempts: 12,
                        waitedMs: 60_000,
                    })
                ),
        } as unknown as ScrubClient
        const batcher = new ImageBatcher(
            new FakeStore() as unknown as ImageShardStore,
            new FakeOffsets(),
            poisonClient,
            options,
            0,
            {
                park: (image) => Promise.resolve(void parked.push({ headers: image.headers, bytes: image.bytes })),
            }
        )
        const png = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
        const compressed = gzipSync(png)
        const ref = urlRef(hashImageBytes(CONTENT_KEY, Buffer.from('https://example.com/poison.png')))

        await batcher.handleBatch(
            [
                msg(0, 0, pt(1), compressed, ref, [
                    { 'content-type': Buffer.from('image/png') },
                    { 'content-encoding': Buffer.from('gzip') },
                ]),
            ],
            1
        )

        expect(parked).toEqual([
            {
                bytes: compressed,
                headers: { 'content-type': 'image/png', 'content-encoding': 'gzip' },
            },
        ])
    })

    it('refuses to start when concurrency is too low for dead-lettering to be reachable', () => {
        // The poison gate can only ever count successes from slots running alongside the image it is
        // judging: the batch holding that image cannot finish, and the pod cannot poll for more work
        // until it does. At or below the threshold the gate is unreachable, so the first image the
        // sidecar cannot scrub stops the pod consuming for good. Failing at boot beats deadlocking
        // in traffic, where it presents as a pod that is Ready and quietly doing nothing.
        expect(
            () =>
                new ImageBatcher(
                    new FakeStore() as unknown as ImageShardStore,
                    new FakeOffsets(),
                    scrubClient,
                    { ...options, scrubConcurrency: 2 },
                    0,
                    { park: () => Promise.resolve() }
                )
        ).toThrow('scrubConcurrency must exceed')
    })

    it('retries a failed park rather than failing the batch over it', async () => {
        // Ordering is the whole safety property here. Marking the ref or retiring the slot before the
        // bytes are durably parked would advance the offset over an image held nowhere at all.
        //
        // Letting the failure escape is worse still than the stall it would replace: the Kafka loop
        // exits the process on any batch error, so a dead-letter topic that is missing, on the wrong
        // cluster, or smaller than a source image would crash-loop every pod in the lane on the same
        // message. Retrying leaves the image where it was, which is what this lane did before a
        // dead-letter topic existed.
        const store = new FakeStore()
        const offsets = new FakeOffsets()
        const poisonClient = {
            scrub: () =>
                Promise.reject(
                    new ScrubPoisoned('cannot process', {
                        reason: 'transport',
                        lastError: 'sidecar responded 500',
                        attempts: 12,
                        waitedMs: 60_000,
                    })
                ),
        } as unknown as ScrubClient
        let parkAttempts = 0
        const batcher = new ImageBatcher(store as unknown as ImageShardStore, offsets, poisonClient, options, 0, {
            park: () => {
                parkAttempts += 1
                return parkAttempts < 3 ? Promise.reject(new Error('dlq produce failed')) : Promise.resolve()
            },
        })

        await expect(batcher.handleBatch([msg(0, 0, pt(1), Buffer.from('poison'))], 1)).resolves.toBeUndefined()

        expect(parkAttempts).toBe(3)
        // The offset only moves once the bytes are somewhere, never while parking is still failing.
        expect(offsets.received.flat().map((o) => o.offset)).toEqual([1])
    })

    it('returns when stopped, so shutdown does not wait on an unresponsive sidecar', async () => {
        // disconnect() awaits the running batch, and the scrub client now waits on a busy sidecar
        // rather than giving up, so a batch against a sidecar that is down never returns on its own.
        // Without the interrupt a graceful stop runs to the termination grace period and is SIGKILLed.
        const store = new FakeStore()
        const offsets = new FakeOffsets()
        const hangingClient = {
            scrub: (_b: Buffer, signal: AbortSignal) =>
                new Promise<Buffer>((_resolve, reject) =>
                    signal.addEventListener('abort', () => reject(new Error('scrub batch aborted')), { once: true })
                ),
        } as unknown as ScrubClient
        const batcher = new ImageBatcher(store as unknown as ImageShardStore, offsets, hangingClient, options, 0)
        const startBatch = jest.spyOn(ImageScrubConsumerMetrics, 'startBatch')
        const finishBatch = jest.spyOn(ImageScrubConsumerMetrics, 'finishBatch')

        const running = batcher.handleBatch([msg(0, 0, pt(1), Buffer.from('a'))], 1)
        expect(startBatch).toHaveBeenCalledTimes(1)
        expect(finishBatch).not.toHaveBeenCalled()
        batcher.stop()

        await expect(running).resolves.toBeUndefined()
        expect(finishBatch).toHaveBeenCalledTimes(1)
        // Nothing finished, so nothing may be committed over: the image replays under the next owner.
        expect(offsets.received.flat()).toEqual([])
        expect(store.writes).toHaveLength(0)
    })

    it('discards offsets for a partition a rebalance already revoked, rather than exiting', async () => {
        // librdkafka raises ERR__STATE for a partition we no longer hold. The shard is already on S3,
        // so the span simply rescrubs under its new owner. Propagating it exits the process, and a
        // pod exiting is itself what triggers the next rebalance.
        const store = new FakeStore()
        const revoked = new FakeOffsets()
        revoked.offsetsStore = () => {
            throw Object.assign(new Error('Local: Erroneous state'), { code: -172 })
        }
        const batcher = new ImageBatcher(store as unknown as ImageShardStore, revoked, scrubClient, options, 0)

        await expect(batcher.handleBatch([msg(0, 0, pt(1), Buffer.from('a'))], 1)).resolves.toBeUndefined()
        expect(store.writes).toHaveLength(1)
    })

    it('still fails the batch when storing offsets fails for any other reason', async () => {
        const store = new FakeStore()
        const broken = new FakeOffsets()
        broken.offsetsStore = () => {
            throw Object.assign(new Error('Broker: Not coordinator'), { code: 16 })
        }
        const batcher = new ImageBatcher(store as unknown as ImageShardStore, broken, scrubClient, options, 0)

        await expect(batcher.handleBatch([msg(0, 0, pt(1), Buffer.from('a'))], 1)).rejects.toThrow('Not coordinator')
    })
})
