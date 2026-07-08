import { elementToSelector } from 'lib/utils/actions'

import { ElementType } from '~/types'

describe('elementToSelector', () => {
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

    it('ignores unstable useId-derived attr_id and falls back to tag + class', () => {
        const element = {
            tag_name: 'button',
            attr_id: 'radix-:rr:',
            attr_class: ['btn'],
        } as ElementType

        const actual = elementToSelector(element, [])
        expect(actual).toEqual('button.btn')
    })

    it('ignores an unstable useId-derived data attribute value and falls back', () => {
        const element = {
            tag_name: 'div',
            attributes: { 'attr__data-id': 'base-ui-:rg:-viewport' },
        } as unknown as ElementType

        const actual = elementToSelector(element, ['data-id'])
        expect(actual).toEqual('div')
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
