import { PropertyOperator } from '~/types'

import { getValidationError, withRegexDraft } from './OperatorValueSelect'

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

    it.each([
        { case: 'a cleared single-value draft', value: '(?=bad)', draft: '', expectError: false },
        { case: 'a valid draft that replaces an invalid pattern', value: '(?=bad)', draft: '^ok$', expectError: false },
        { case: 'an invalid draft over a valid pattern', value: '^ok$', draft: '(?=bad)', expectError: true },
        {
            case: 'an invalid draft added to multi-value patterns',
            value: ['^ok$'],
            draft: '(?<=bad)',
            expectError: true,
        },
        { case: 'no draft over an invalid pattern', value: '(?=bad)', draft: null, expectError: true },
    ])('validates the regex draft text for $case', ({ value, draft, expectError }) => {
        const valueToValidate = withRegexDraft(value, draft)
        const error = valueToValidate ? getValidationError(PropertyOperator.Regex, valueToValidate) : null

        expect(error !== null).toBe(expectError)
    })
})
