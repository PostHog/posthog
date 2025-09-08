import { sanitizeForUTF8 } from '~/utils/strings'

describe('string utils', () => {
    test.each(['\ud83c', '\uDC00', '\ud83d'])('should replace lone surrogate pairs', (loneSurrogatePair) => {
        const sanitized = sanitizeForUTF8(`string truncated at lone surrogate pair ${loneSurrogatePair}`)
        expect(sanitized).not.toContain(loneSurrogatePair)
        expect(sanitized).toContain('\uFFFD') // replacement character
    })
})
