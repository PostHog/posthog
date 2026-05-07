import { calculateSlot } from './cluster-slot'

describe('calculateSlot', () => {
    // Reference values from Redis: https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/
    it.each([
        // Reference values cross-checked against `redis-cli CLUSTER KEYSLOT <key>`.
        ['foo', 12182],
        ['bar', 5061],
        ['', 0],
        ['a', 15495],
    ])('matches Redis-spec CRC16 for %s', (key, expectedSlot) => {
        expect(calculateSlot(key)).toBe(expectedSlot)
    })

    it('honors hash tags — only the tag content is hashed', () => {
        // Anything wrapped in {} is hashed instead of the full key, so all of
        // these collapse to the same slot.
        const tag = '{user1000}'
        expect(calculateSlot(`${tag}.following`)).toBe(calculateSlot(`${tag}.followers`))
        expect(calculateSlot(`${tag}.following`)).toBe(calculateSlot('user1000'))
    })

    it('falls back to full-key hash when {} is empty', () => {
        // Empty `{}` is treated as no hash tag — full key gets hashed.
        expect(calculateSlot('{}foo')).toBe(calculateSlot('{}foo'))
        expect(calculateSlot('{}foo')).not.toBe(calculateSlot('foo'))
    })

    it('falls back to full-key hash when } is missing', () => {
        // No closing brace = no hash tag.
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
