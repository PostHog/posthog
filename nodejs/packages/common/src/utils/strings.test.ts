import { sanitizeForUTF8 } from '~/utils/strings'

describe('string utils', () => {
    test.each(['\ud83c', '\uDC00', '\ud83d', '\ude00'])('should replace lone surrogate pairs', (loneSurrogatePair) => {
        const sanitized = sanitizeForUTF8(`string truncated at lone surrogate pair ${loneSurrogatePair}`)
        expect(sanitized).not.toContain(loneSurrogatePair)
        expect(sanitized).toContain('\uFFFD') // replacement character
    })

    test('should preserve valid emoji and multi-byte characters', () => {
        const input = '👍 Hello 世界 🎉'
        expect(sanitizeForUTF8(input)).toBe(input)
    })

    test('should handle lone surrogate at start (truncated emoji end)', () => {
        const truncatedEmoji = '\ude00 World' // Second half of 😀
        const sanitized = sanitizeForUTF8(truncatedEmoji)
        expect(sanitized).toBe('\uFFFD World')
    })

    test('should handle multiple broken surrogates', () => {
        const input = '\ud83d text \ude00 more \ud83d\ud83d end'
        const sanitized = sanitizeForUTF8(input)
        expect(sanitized).toBe('\uFFFD text \uFFFD more \uFFFD\uFFFD end')
    })

    test('should handle strings with valid surrogate pairs', () => {
        const validPairs = '𝄞𝐀𝐁𝐂' // Mathematical bold characters using surrogate pairs
        expect(sanitizeForUTF8(validPairs)).toBe(validPairs)
    })

    test('should handle mixed valid and invalid surrogates', () => {
        const mixed = '😀\ud83d😀\ude00😀' // valid emoji, lone high, valid emoji, lone low, valid emoji
        const sanitized = sanitizeForUTF8(mixed)
        expect(sanitized).toBe('😀\uFFFD😀\uFFFD😀')
    })
})
