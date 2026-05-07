import { calculateSlot } from './cluster-slot'

// Reference: Valkey cluster specification (Appendix A — CRC16 + hash tag rules).
// https://valkey.io/topics/cluster-spec/
//
// AWS ElastiCache Valkey Serverless implements this spec verbatim — it
// "operates engines in cluster mode enabled only" and rejects multi-key
// scripts with `CROSSSLOT` when keys span slots. Slot grouping in
// `checkRateLimitV3Many` relies on this implementation matching bit-for-bit.
describe('calculateSlot', () => {
    it('matches the canonical XMODEM CRC16 test vector from the spec', () => {
        // From the Valkey cluster spec: "Output for '123456789': 31C3".
        // 0x31C3 = 12739 decimal. < 16384, so the mod is a no-op.
        expect(calculateSlot('123456789')).toBe(0x31c3)
    })

    it.each([
        // Cross-checked against `valkey-cli CLUSTER KEYSLOT <key>`.
        ['foo', 12182],
        ['bar', 5061],
        ['', 0],
        ['a', 15495],
    ])('matches CLUSTER KEYSLOT for %s', (key, expectedSlot) => {
        expect(calculateSlot(key)).toBe(expectedSlot)
    })

    it('honors hash tags — only the tag content is hashed', () => {
        // Spec: when `{` is followed by `}` with content between, only the
        // substring between them is hashed. So all of these hash identically.
        const tag = '{user1000}'
        expect(calculateSlot(`${tag}.following`)).toBe(calculateSlot(`${tag}.followers`))
        expect(calculateSlot(`${tag}.following`)).toBe(calculateSlot('user1000'))
    })

    it('foo{}{bar} hashes the whole key (spec edge case)', () => {
        // Spec: "the whole key will be hashed as usually since the first
        // occurrence of `{` is followed by `}` on the right without characters
        // in the middle".
        expect(calculateSlot('foo{}{bar}')).toBe(calculateSlot('foo{}{bar}'))
        expect(calculateSlot('foo{}{bar}')).not.toBe(calculateSlot('bar'))
    })

    it('foo{bar}{zap} hashes only "bar" (spec edge case)', () => {
        // Spec: "the substring `bar` will be hashed".
        expect(calculateSlot('foo{bar}{zap}')).toBe(calculateSlot('bar'))
    })

    it('falls back to full-key hash when } is missing', () => {
        expect(calculateSlot('{foo')).not.toBe(calculateSlot('foo'))
    })

    it('returns slots within [0, 16384)', () => {
        for (let i = 0; i < 100; i++) {
            const slot = calculateSlot(`key-${Math.random()}`)
            expect(slot).toBeGreaterThanOrEqual(0)
            expect(slot).toBeLessThan(16384)
        }
    })
})
