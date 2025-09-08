import { sanitizeForUTF8 } from '~/utils/strings'

describe('string utils', () => {
    test.each([
        'Hello \ud83d World\ud83d',
        'Hello \ud83c World',
        'Hello \uDC00 World',
        'Hello \ud83d World\ud83d',
        'Hello \ud83d World\ud83d ',
    ])('should replace lone surrogate pairs', (s) => {
        const sanitized = sanitizeForUTF8(s)
        expect(sanitized).not.toContain('\ud83c')
        expect(sanitized).not.toContain('\ud83c')
        expect(sanitized).not.toContain('\uDC00')
        expect(sanitized).toMatchSnapshot()
    })
})
