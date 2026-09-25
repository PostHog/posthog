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

    it.each([
        ['radix-:rr:', 'a React useId value embedded by Radix'],
        ['base-ui-:rg:-viewport', 'a React useId value embedded by Base UI'],
        ['«r5»', 'a React 19 useId value'],
    ])('ignores the unstable id %s (%s) and falls back to tag + class', (attr_id) => {
        const element = {
            tag_name: 'button',
            attr_id,
            attr_class: ['btn'],
        } as ElementType

        expect(elementToSelector(element, [])).toEqual('button.btn')
    })

    it('keeps anchoring to a stable id', () => {
        const element = {
            tag_name: 'button',
            attr_id: 'checkout-submit',
        } as ElementType

        expect(elementToSelector(element, [])).toEqual('[id="checkout-submit"]')
    })

    it('ignores an unstable data attribute value and falls back', () => {
        const element = {
            tag_name: 'div',
            attributes: { 'attr__data-id': 'base-ui-:rg:-viewport' },
        } as unknown as ElementType

        expect(elementToSelector(element, ['data-id'])).toEqual('div')
    })

    it('continues to a later configured data attribute when the first is unstable', () => {
        const element = {
            tag_name: 'div',
            attributes: { 'attr__data-id': 'base-ui-:rg:-viewport', 'attr__data-testid': 'save-button' },
        } as unknown as ElementType

        expect(elementToSelector(element, ['data-id', 'data-testid'])).toEqual('[data-testid="save-button"]')
    })

    it('continues to a later matching attribute key when a wildcard value is unstable', () => {
        const element = {
            tag_name: 'div',
            attributes: { 'attr__data-id-generated': 'radix-:rr:', 'attr__data-id-name': 'save-button' },
        } as unknown as ElementType

        expect(elementToSelector(element, ['data-id-*'])).toEqual('[data-id-name="save-button"]')
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
