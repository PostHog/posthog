import { hashImageBytes, imageRef, isImageRef } from './content-ref'
import { type ImageInput, type ImageScrubEmitDeps, type TopicMessage, emitImagesForScrub } from './producer'
import { getScrubMethodForImage } from './scrub-method'

/** In-memory reserve/release/produce that counts round-trips, so we can assert one call per batch.
 *  Mirrors the ordered semantics of a Redis SET NX pipeline: within one batch the first occurrence of
 *  a key is fresh. */
function fakeDeps(): {
    deps: ImageScrubEmitDeps
    keys: Map<string, number>
    sent: TopicMessage[]
    calls: { reserve: number; release: number; produce: number }
    failProduce: () => void
    healProduce: () => void
} {
    const keys = new Map<string, number>()
    const sent: TopicMessage[] = []
    const calls = { reserve: 0, release: 0, produce: 0 }
    let produceFails = false
    const deps: ImageScrubEmitDeps = {
        setBatchContentKeysRedis: (ks, ttl) => {
            calls.reserve++
            return Promise.resolve(
                ks.map((k) => {
                    if (keys.has(k)) {
                        return false
                    }
                    keys.set(k, ttl)
                    return true
                })
            )
        },
        deleteBatchContentKeysRedis: (ks) => {
            calls.release++
            ks.forEach((k) => keys.delete(k))
            return Promise.resolve()
        },
        produceBatchImagesKafka: (messages) => {
            calls.produce++
            if (produceFails) {
                return Promise.reject(new Error('broker down'))
            }
            sent.push(...messages)
            return Promise.resolve()
        },
    }
    return {
        deps,
        keys,
        sent,
        calls,
        failProduce: () => (produceFails = true),
        healProduce: () => (produceFails = false),
    }
}

const img = (teamId: number, s: string): ImageInput => ({ teamId, bytes: Buffer.from(s) })

describe('ml-mirror/image-scrub', () => {
    // CONTRACT: these golden vectors MUST match the consumer's content-ref (its dev/content-ref.test.ts
    // asserts the same input -> hash/ref/s3-key), or references won't resolve. Change both together.
    describe('content-ref contract (golden vectors)', () => {
        const INPUT = 'posthog-image-scrub-contract-v1'
        const HASH = 'q1YIODUgcFH6CgV1DOI4SU'

        it('hashes to the golden 22-char base64url content hash', () => {
            expect(hashImageBytes(Buffer.from(INPUT))).toBe(HASH)
        })

        it('builds the golden team-scoped reference', () => {
            expect(imageRef(42, HASH)).toBe(`image:42:${HASH}`)
        })

        it('is team-scoped: same bytes in different teams get different refs (tenant isolation)', () => {
            const bytes = Buffer.from('logo-png-bytes')
            expect(imageRef(42, hashImageBytes(bytes))).not.toBe(imageRef(99, hashImageBytes(bytes)))
        })

        it('accepts a reference and rejects a raw data URI', () => {
            expect(isImageRef(imageRef(7, hashImageBytes(Buffer.from('x'))))).toBe(true)
            expect(isImageRef('data:image/png;base64,iVBORw0KG')).toBe(false)
        })
    })

    describe('getScrubMethodForImage', () => {
        it('passes tiny images through, for any source', () => {
            expect(getScrubMethodForImage({ source: 'img', width: 16, height: 8, byteLength: 200 })).toBe('passthrough')
            expect(getScrubMethodForImage({ source: 'canvas', width: 10, height: 10, byteLength: 200 })).toBe(
                'passthrough'
            )
        })

        it('does NOT pass through a large image with crafted tiny dimensions (byte floor)', () => {
            // rrweb width/height are attacker-controlled; a 1x1 declared on a 900KB image must still be
            // scrubbed, not passed through unredacted.
            expect(getScrubMethodForImage({ source: 'img', width: 1, height: 1, byteLength: 900_000 })).toBe(
                'advancedScrub'
            )
            expect(getScrubMethodForImage({ source: 'img', width: 16, height: 16, byteLength: 50_000 })).toBe(
                'advancedScrub'
            )
        })

        it('routes canvas to the cheap in-process blur (dynamic, no dedup)', () => {
            expect(getScrubMethodForImage({ source: 'canvas', width: 800, height: 600, byteLength: 5000 })).toBe(
                'cheapBlur'
            )
        })

        it('falls back to cheap when too big for the topic', () => {
            expect(getScrubMethodForImage({ source: 'img', width: 4000, height: 4000, byteLength: 2_000_000 })).toBe(
                'cheapBlur'
            )
        })

        it('routes static <img>/media raster to the advanced topic path', () => {
            expect(getScrubMethodForImage({ source: 'img', width: 300, height: 300, byteLength: 5000 })).toBe(
                'advancedScrub'
            )
            expect(getScrubMethodForImage({ source: 'media', width: 300, height: 300, byteLength: 5000 })).toBe(
                'advancedScrub'
            )
        })

        it('scrubs unknown-size images rather than passing them through', () => {
            expect(getScrubMethodForImage({ source: 'img', byteLength: 5000 })).toBe('advancedScrub')
        })
    })

    describe('emitImagesForScrub', () => {
        it('dedups + posts in exactly ONE redis round-trip and ONE produce', async () => {
            const { deps, sent, calls } = fakeDeps()
            const images = Array.from({ length: 8 }, (_, i) => img(42, `image-${i}`))

            const results = await emitImagesForScrub(images, deps)

            expect(calls.reserve).toBe(1) // one call per batch, regardless of image count
            expect(calls.produce).toBe(1)
            expect(results).toHaveLength(8)
            expect(results.every((r) => r.posted)).toBe(true)
            expect(sent).toHaveLength(8)
        })

        it('posts duplicates within a batch and across batches only once', async () => {
            const { deps, sent } = fakeDeps()
            const dup = img(42, 'same-image')

            const first = await emitImagesForScrub([dup, dup, img(42, 'other')], deps)
            expect(first.map((r) => r.posted)).toEqual([true, false, true]) // 2nd is the in-batch duplicate
            expect(sent).toHaveLength(2)

            const second = await emitImagesForScrub([dup], deps)
            expect(second[0].posted).toBe(false) // already posted in the previous batch
            expect(sent).toHaveLength(2)
        })

        it('posts the same image in two teams twice (separate dedup keys)', async () => {
            const { deps, sent } = fakeDeps()
            const results = await emitImagesForScrub([img(42, 'shared'), img(99, 'shared')], deps)
            expect(results.map((r) => r.posted)).toEqual([true, true])
            expect(sent).toHaveLength(2)
        })

        it('releases the batch reservations on a produce failure so later sightings can retry', async () => {
            const { deps, sent, calls, keys, failProduce, healProduce } = fakeDeps()
            failProduce()
            const images = [img(42, 'a'), img(42, 'b')]

            await expect(emitImagesForScrub(images, deps)).rejects.toThrow()
            expect(calls.release).toBe(1)
            expect(keys.size).toBe(0) // both reservations rolled back

            healProduce()
            const retry = await emitImagesForScrub(images, deps)
            expect(retry.every((r) => r.posted)).toBe(true)
            expect(sent).toHaveLength(2)
        })

        it('does no work for an empty batch', async () => {
            const { deps, calls } = fakeDeps()
            expect(await emitImagesForScrub([], deps)).toEqual([])
            expect(calls.reserve).toBe(0)
            expect(calls.produce).toBe(0)
        })
    })
})
