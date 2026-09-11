import { elementToSelector, matchesDataAttribute } from 'lib/utils/actions'

import { ElementType } from '~/types'

describe('elementToSelector', () => {
    it.each([
        ['data.*', 'data.name', true],
        ['data.*', 'dataXname', false],
        ['*', 'data\nname', false],
        ['data*', 'data\n', false],
        ['data*', 'data\r', false],
        ['data*', 'data\u2028', false],
        ['data*', 'data\u2029', false],
        ['data\n*', 'data\nname', true],
        ['*\ud83d*', '\ud83d\ude00', true],
    ])('matches data attribute %p against %p', (pattern, attribute, expected) => {
        const element = { attributes: { [`attr__${attribute}`]: 'value' } } as unknown as ElementType
        expect(matchesDataAttribute(element, [pattern])).toBe(expected ? attribute : undefined)
    })

    it('keeps configured attribute priority and object key order', () => {
        const element = { attributes: { attr__first: '1', attr__second: '2' } } as unknown as ElementType
        expect(matchesDataAttribute(element, ['second', '*'])).toBe('second')
        expect(matchesDataAttribute(element, ['*'])).toBe('first')
        expect(matchesDataAttribute({} as ElementType, ['*'])).toBeUndefined()
    })

    it('rejects repeated wildcard nonmatches', () => {
        const element = { attributes: { [`attr__${'a'.repeat(2000)}`]: 'value' } } as unknown as ElementType
        expect(matchesDataAttribute(element, ['*a'.repeat(24) + 'b'])).toBeUndefined()
    })

    it('generates a data attr not an #ID', () => {
        const element = {
            attr_id: 'tomato',
        } as ElementType

        const actual = elementToSelector(element, [])
        expect(actual).toEqual('[id="tomato"]')
    })

    it('generates an incorrect class selector', () => {
        const element = {
            attr_class: ['potato', 'soup'],
        } as ElementType

        const actual = elementToSelector(element, [])
        expect(actual).toEqual('.potato.soup')
    })

    const dataAttributeValueCases = [
        {
            name: 'keeps dots unescaped so backend literal matching still works',
            value: 'user.settings.save',
            expected: '[data-attr="user.settings.save"]',
        },
        {
            name: 'escapes quotes so a value cannot break out of the selector',
            value: 'x"],[id="other',
            expected: '[data-attr="x\\"],[id=\\"other"]',
        },
        {
            name: 'escapes backslashes before quotes',
            value: 'a\\"b',
            expected: '[data-attr="a\\\\\\"b"]',
        },
    ]

    it.each(dataAttributeValueCases)('$name', ({ value, expected }) => {
        const element = {
            attributes: { 'attr__data-attr': value },
        } as unknown as ElementType

        const actual = elementToSelector(element, ['data-attr'])
        expect(actual).toEqual(expected)
    })
})
