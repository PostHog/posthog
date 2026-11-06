import { RE2Engine, loadRE2 } from 'lib/utils/regexp'

import { PropertyOperator } from '~/types'

import { getValidationError } from './OperatorValueSelect'

describe('getValidationError', () => {
    let re2: RE2Engine

    beforeAll(async () => {
        re2 = await loadRE2()
    })

    // A visited_page filter ORs several regex values, so the value is an array. RE2JS.compile
    // used to receive the array directly and throw "this.str.codePointAt is not a function",
    // surfacing that internal error to the user in the filter editor.
    it('accepts every valid pattern of a multi-value regex', () => {
        const value = ['/project/[^/]+/replay/home', '/project/[^/]+/replay/playlists']

        expect(getValidationError(PropertyOperator.Regex, value, re2)).toBeNull()
    })

    it.each([
        ['one pattern of a multi-value regex', ['/valid/path', '/bad(unclosed']],
        ['a single-value regex', '(unclosed'],
    ])('reports an invalid pattern in %s', (_name, value) => {
        const error = getValidationError(PropertyOperator.Regex, value, re2)

        expect(error).not.toBeNull()
        expect(error).not.toContain('codePointAt')
    })

    it('reports no regex error before the RE2 engine loads', () => {
        expect(getValidationError(PropertyOperator.Regex, '(unclosed', null)).toBeNull()
    })
})
