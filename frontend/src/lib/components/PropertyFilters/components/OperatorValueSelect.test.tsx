import { PropertyOperator } from '~/types'

import { getValidationError } from './OperatorValueSelect'

describe('getValidationError', () => {
    it('validates every pattern of a multi-value regex filter without crashing on the array', () => {
        // A visited_page filter ORs several regex values, so the value is an array. RE2JS.compile
        // used to receive the array directly and throw "this.str.codePointAt is not a function",
        // surfacing that internal error to the user in the filter editor.
        const value = ['/project/[^/]+/replay/home', '/project/[^/]+/replay/playlists']

        expect(getValidationError(PropertyOperator.Regex, value)).toBeNull()
    })

    it('reports the first invalid pattern in a multi-value regex filter', () => {
        const value = ['/valid/path', '/bad(unclosed']

        const error = getValidationError(PropertyOperator.Regex, value)

        expect(error).not.toBeNull()
        expect(error).not.toContain('codePointAt')
    })

    it('still reports an invalid single-value regex', () => {
        expect(getValidationError(PropertyOperator.Regex, '(unclosed')).not.toBeNull()
    })
})
