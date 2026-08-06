import { murmur2, murmur2Partition } from './murmur2'

describe('murmur2', () => {
    // Published Kafka murmur2 vectors, identical to the Rust pin in
    // rust/cohort-stream-processor/src/partitions/partitioner.rs. Expected values are signed i32, so
    // we compare the unsigned hash reinterpreted with `| 0`.
    const publishedVectors: [string, number][] = [
        ['21', -973932308],
        ['foobar', -790332482],
        ['a-little-bit-long-string', -985981536],
        ['a-little-bit-longer-string', -1486304829],
        ['lkjh234lh9fiuh90y23oiuhsafujhadof229phr9h19h89h8', -58897971],
        ['abc', 479470107],
    ]

    it.each(publishedVectors)('matches the published Kafka vector for %p', (input, expected) => {
        expect(murmur2(Buffer.from(input, 'utf8')) | 0).toBe(expected)
    })

    it('reproduces the negative-hash vector through the positivity mask', () => {
        // Raw hash is negative (high bit set); the mask must clear it before modulo.
        const raw = murmur2(Buffer.from('a-little-bit-long-string', 'utf8'))
        expect(raw | 0).toBeLessThan(0)
        expect(murmur2Partition('a-little-bit-long-string', 64)).toBeGreaterThanOrEqual(0)
        expect(murmur2Partition('a-little-bit-long-string', 64)).toBeLessThan(64)
    })

    it('produces identical output for a string key and its UTF-8 Buffer', () => {
        const key = '2:01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        expect(murmur2Partition(key, 64)).toBe(murmur2Partition(Buffer.from(key, 'utf8'), 64))
    })

    // Cross-language fixture: the partition partitioner.rs::partition_for computes for this key at
    // 64 partitions (raw murmur2 = 989609914, 989609914 % 64 = 58). A CRC32 regression would land
    // elsewhere.
    it('matches the Rust partitioner for the merge-key fixture', () => {
        const key = '2:01928aaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        expect(murmur2(Buffer.from(key, 'utf8')) | 0).toBe(989609914)
        expect(murmur2Partition(key, 64)).toBe(58)
    })

    it('always returns a partition within range', () => {
        for (const [input] of publishedVectors) {
            const partition = murmur2Partition(input, 64)
            expect(partition).toBeGreaterThanOrEqual(0)
            expect(partition).toBeLessThan(64)
        }
    })
})
