import { Counter, register } from 'prom-client'

import { RefDedupCache } from './ref-dedup-cache'

describe('RefDedupCache', () => {
    async function probe(cache: string, verdict: 'would_hit' | 'would_miss'): Promise<number> {
        const metric = register.getSingleMetric('ml_mirror_ref_cache_capacity_probe_total') as Counter | undefined
        const data = await metric?.get()
        const sample = data?.values.find((v) => v.labels.cache === cache && v.labels.verdict === verdict)
        return sample?.value ?? 0
    }

    it('separates misses a bigger cache would have caught from ones it would not', async () => {
        // The whole point of the probe is to tell "the working set does not fit" apart from "these
        // duplicates were always too far apart to cache". Both verdicts have to move: a probe stuck
        // on would_miss reads as a correctly sized cache and we stop looking, and one stuck on
        // would_hit sends us buying memory that buys nothing. Sample every ref so it is deterministic.
        const name = 'test_capacity_probe'
        const cache = new RefDedupCache(name, 2, 1)
        cache.add('a')
        cache.add('b')
        cache.add('c') // evicts 'a'

        expect(cache.has('a')).toBe(false)
        expect(await probe(name, 'would_hit')).toBe(1)

        expect(cache.has('never-seen')).toBe(false)
        expect(await probe(name, 'would_miss')).toBe(1)
        expect(await probe(name, 'would_hit')).toBe(1)
    })

    it('does not probe while the cache still has room, so an unfilled cache reads as sized correctly', async () => {
        // Evictions are the only thing that can put a ref in the ghost list, so a cache that never
        // fills must report no would_hit at all rather than blaming capacity for ordinary misses.
        const name = 'test_unfilled'
        const cache = new RefDedupCache(name, 100, 1)
        cache.add('a')

        expect(cache.has('b')).toBe(false)
        expect(await probe(name, 'would_hit')).toBe(0)
        expect(await probe(name, 'would_miss')).toBe(1)
    })
})
