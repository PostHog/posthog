import { decodeCanonicalBase64, isCanonicalBase64 } from './base64'

const BLOB = Buffer.alloc(9000, 5)
const B64 = BLOB.toString('base64')

describe('canonical base64 core', () => {
    it('decodes canonical base64 to the exact bytes', () => {
        expect(decodeCanonicalBase64(B64)?.equals(BLOB)).toBe(true)
    })

    it.each([
        ['interior whitespace', `${B64.slice(0, 6000)}\n${B64.slice(6001)}`],
        ['interior padding', 'AAAA=AAA'],
        ['base64url dash', 'AAA-AAAA'.repeat(1024)],
        ['base64url underscore', 'AAA_AAAA'.repeat(1024)],
        ['length not multiple of 4', 'AAAAA'],
        ['nonzero discarded bits, double padding', 'AAAAAB=='],
        ['nonzero discarded bits, single padding', 'AAAAAAB='],
        ['empty string', ''],
    ])('rejects non-canonical input: %s', (_name, candidate) => {
        expect(decodeCanonicalBase64(candidate)).toBeNull()
    })

    it.each([
        ['zero discarded bits, double padding', 'AAAAAA=='],
        ['zero discarded bits, single padding', 'AAAAAAA='],
    ])('accepts canonical padded input: %s', (_name, candidate) => {
        expect(decodeCanonicalBase64(candidate)).not.toBeNull()
    })

    it('is a type guard rejecting non-strings', () => {
        expect(isCanonicalBase64(12345)).toBe(false)
        expect(isCanonicalBase64(B64)).toBe(true)
    })
})
