import escapeStringRegexp from 'escape-string-regexp'

import { StringMatching } from '../../types'
import { matchString } from './action-matcher'

describe('matchString', () => {
    it('preserves SQL wildcard substring matching on UTF-16 strings', () => {
        const words = ['', 'a', 'b', '%', '_', '.', '\\', '\n', '\r', '\u2028', '\u2029', '😀']
        const samples = [...words, ...words.flatMap((a) => words.map((b) => a + b))]
        for (const pattern of samples) {
            const native = new RegExp(escapeStringRegexp(pattern).replace(/_/g, '.').replace(/%/g, '.*'))
            for (const input of samples) {
                expect(matchString(input, pattern, StringMatching.Contains)).toBe(native.test(input))
            }
        }
    })
})
