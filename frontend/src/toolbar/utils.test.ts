import { denyAllAttributesExceptAllowlist } from './utils'

describe('matching data attributes', () => {
    const testCases = [
        { selector: '[data-attr="something"]', dataAttributes: ['data-attr'], expected: true },
        { selector: '[data-attr="something"]', dataAttributes: ['data-*'], expected: true },
        { selector: '[data-not-me="something"]', dataAttributes: ['data-attr'], expected: false },
        { selector: '[data-attr="something"]', dataAttributes: ['data-not-me'], expected: false },
        { selector: '[href="something"]', dataAttributes: ['data-not-me'], expected: false },
        { selector: '[data-attr="something"]', dataAttributes: [], expected: false },
        { selector: '#something', dataAttributes: ['data-attr'], expected: false },
        { selector: '.something', dataAttributes: ['data-attr'], expected: false },
    ]
    testCases.forEach(({ selector, dataAttributes, expected }) => {
        it(`should ${expected ? '' : 'not '}match ${selector} with ${JSON.stringify(dataAttributes)}`, () => {
            expect(denyAllAttributesExceptAllowlist(selector, dataAttributes)).toEqual(expected)
        })
    })
})
