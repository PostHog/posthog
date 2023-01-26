import { denyAllAttributesExceptAllowlist } from './utils'

describe('matching data attributes', () => {
    // the finder dependency sends just the name of the attribute in an attribute matcher
    // so we don't need to handle matching non-attribute values like #an-id or .a-class
    const testCases = [
        { selector: 'data-attr', dataAttributes: ['data-attr'], expected: true },
        { selector: 'data-attr', dataAttributes: ['data-*'], expected: true },
        { selector: 'data-not-me', dataAttributes: ['data-attr'], expected: false },
        { selector: 'data-attr', dataAttributes: ['data-not-me'], expected: false },
        { selector: 'href', dataAttributes: ['data-not-me'], expected: false },
        { selector: 'href', dataAttributes: [], expected: false },
        { selector: 'data-attr', dataAttributes: [], expected: false },
    ]
    testCases.forEach(({ selector, dataAttributes, expected }) => {
        it(`should ${expected ? '' : 'not '}match ${selector} with ${JSON.stringify(dataAttributes)}`, () => {
            expect(denyAllAttributesExceptAllowlist(selector, dataAttributes)).toEqual(expected)
        })
    })
})
