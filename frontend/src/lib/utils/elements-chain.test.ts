import { chainToElements, parseElementAttributes, splitElementsChain } from './elements-chain'

describe('chainToElements', () => {
    it('parses a well-formed chain', () => {
        const elements = chainToElements(
            'a.small:href="/a-url"nth-child="1"nth-of-type="0"text="say \\"hi\\"";button:nth-child="0"nth-of-type="0"'
        )
        expect(elements).toMatchObject([
            { tag_name: 'a', attr_class: ['small'], href: '/a-url', nth_child: 1, text: 'say \\"hi\\"', order: 0 },
            { tag_name: 'button', nth_child: 0, nth_of_type: 0, order: 1 },
        ])
    })

    it('keeps a colon in a class name and an empty attribute value', () => {
        const elements = chainToElements('div.sm:flex.x:attr__alt=""href="/a"nth-child="2"')
        expect(elements).toMatchObject([
            { tag_name: 'div', attr_class: ['sm:flex', 'x'], href: '/a', nth_child: 2, attributes: { attr__alt: '' } },
        ])
    })

    it.each([
        ['a long backslash run', 'a:text="' + '\\'.repeat(5000), ['a', '\\'.repeat(5000)]],
        ['a long run of escaped quotes', '"\\'.repeat(5000), Array(5000).fill('\\')],
        ['a quote at the end of the chain', 'button:nth-child="1"text="unclosed', ['button', 'unclosed']],
    ])('ends the element at a quote that is never closed: %s', (_name, chain, expectedTagNames) => {
        const elements = chainToElements(chain)
        expect(elements.map((element) => element.tag_name)).toEqual(expectedTagNames)
        expect(elements.every((element) => element.text === undefined)).toBe(true)
    })

    it('drops a value that ends in a backslash at the end of the chain', () => {
        const elements = chainToElements('button:nth-child="2";a:nth-child="1"href="C:\\"')
        expect(elements).toMatchObject([{ tag_name: 'button' }, { tag_name: 'a', nth_child: 1 }])
        expect(elements[1].href).toBeUndefined()
    })

    it.each([
        ['a value that never closes', 'x="' + 'a'.repeat(80_000), []],
        ['a never-closing value after a closed one', 'href="/a"text="' + '\\"'.repeat(2000), [['href', '/a']]],
        [
            'a backslash before an escaped quote',
            'text="foo\\\\"bar"nth-child="1"',
            [
                ['text', 'foo\\\\"bar'],
                ['nth-child', '1'],
            ],
        ],
    ])('parses attributes with %s', (_name, attributes, expected) => {
        expect(parseElementAttributes(attributes)).toEqual(expected)
    })

    it('splits on whitespace and semicolons outside quotes only', () => {
        expect(splitElementsChain('a:text="x; y"  ;b\tc')).toEqual(['a:text="x; y"', 'b', 'c'])
    })
})
