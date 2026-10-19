import { chainToElements } from './elements-chain'

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

    it('ends the element at a quote that is never closed', () => {
        const elements = chainToElements('a:text="' + '\\'.repeat(5000))
        expect(elements.map((element) => element.tag_name)).toEqual(['a', '\\'.repeat(5000)])
    })
})
