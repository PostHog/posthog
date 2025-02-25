import { chainToElements, elementsToString, extractElements } from '../../../src/utils/db/elements-chain'

describe('elementsToString and chainToElements', () => {
    it('is reversible', () => {
        const elementsString = elementsToString([
            {
                tag_name: 'a',
                href: '/a-url',
                attr_class: ['small'],
                text: 'bla bla',
                attributes: {
                    prop: 'value',
                    number: 33,
                    'data-attr': 'something " that; could mess up',
                    style: 'min-height: 100vh;',
                },
                nth_child: 1,
                nth_of_type: 0,
            },
            { tag_name: 'button', attr_class: ['btn', 'btn-primary'], nth_child: 0, nth_of_type: 0 },
            { tag_name: 'div', nth_child: 0, nth_of_type: 0 },
            { tag_name: 'div', nth_child: 0, nth_of_type: 0, attr_id: 'nested' },
        ])

        expect(elementsString).toEqual(
            [
                'a.small:data-attr="something \\" that; could mess up"href="/a-url"nth-child="1"nth-of-type="0"number="33"prop="value"style="min-height: 100vh;"text="bla bla"',
                'button.btn.btn-primary:nth-child="0"nth-of-type="0"',
                'div:nth-child="0"nth-of-type="0"',
                'div:attr_id="nested"nth-child="0"nth-of-type="0"',
            ].join(';')
        )

        const elements = chainToElements(elementsString, 0, { throwOnError: true })
        expect(elements.length).toBe(4)
        expect(elements[0].tag_name).toEqual('a')
        expect(elements[0].href).toEqual('/a-url')
        expect(elements[0].attr_class).toEqual(['small'])
        expect(elements[0].attributes).toEqual({
            prop: 'value',
            number: '33',
            // NB! The original Python code also does not unescape `\"` -> `"`
            // Could be fixed later, but keeping as is for parity.
            'data-attr': 'something \\" that; could mess up',
            style: 'min-height: 100vh;',
        })
        expect(elements[0].nth_child).toEqual(1)
        expect(elements[0].nth_of_type).toEqual(0)
        expect(elements[1].attr_class).toEqual(['btn', 'btn-primary'])
        expect(elements[3].attr_id).toEqual('nested')
    })

    it('handles empty strings', () => {
        const elements = chainToElements('', 0, { throwOnError: true })
        expect(elements).toEqual([])
    })

    it('handles broken class names', () => {
        const elements = chainToElements('"a........small', 0, { throwOnError: true })
        expect(elements).not.toEqual([])
        expect(elements[0]).toEqual(
            expect.objectContaining({
                tag_name: 'a',
                attr_class: ['small'],
            })
        )
    })

    it('handles element containing quotes and colons', () => {
        const element = {
            tag_name: 'a',
            href: '/a-url',
            attr_class: ['small"', 'xy:z'],
            attributes: {
                attr_class: 'xyz small"',
            },
        }

        const elementsString = elementsToString([element])

        expect(elementsString).toEqual(
            'a.small.xy:z:attr_class="xyz small\\""href="/a-url"nth-child="0"nth-of-type="0"'
        )

        const elements = chainToElements(elementsString, 0, { throwOnError: true })
        expect(elements.length).toEqual(1)
        expect(elements[0]).toEqual(
            expect.objectContaining({
                tag_name: 'a',
                href: '/a-url',
                // :KLUDGE: The tranformation is not fully reversible
                attr_class: ['small', 'xy:z'],
                attributes: {
                    attr_class: 'xyz small\\"',
                },
            })
        )
    })

    it('handles multiple classNames', () => {
        const element = {
            attr_class: ['something', 'another'],
            attributes: {
                attr__class: 'something another',
            },
        }
        const elementsString = elementsToString([element])

        expect(elementsString).toEqual('.another.something:attr__class="something another"nth-child="0"nth-of-type="0"')
        expect(chainToElements(elementsString, 0)).toEqual([expect.objectContaining(element)])
    })
})

describe('extractElements()', () => {
    it('parses simple elements', () => {
        const result = extractElements([
            { tag_name: 'a', nth_child: 1, nth_of_type: 2, attr__class: 'btn btn-sm' },
            { tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' },
        ])

        expect(result).toEqual([
            {
                text: undefined,
                tag_name: 'a',
                href: undefined,
                attr_class: ['btn', 'btn-sm'],
                attr_id: undefined,
                nth_child: 1,
                nth_of_type: 2,
                attributes: { attr__class: 'btn btn-sm' },
            },
            {
                text: '💻',
                tag_name: 'div',
                href: undefined,
                attr_class: undefined,
                attr_id: undefined,
                nth_child: 1,
                nth_of_type: 2,
                attributes: {},
            },
        ])
    })

    it('handles arrays for attr__class', () => {
        const result = extractElements([{ attr__class: ['btn', 'btn-sm'] }])

        expect(result[0]).toEqual(
            expect.objectContaining({
                attr_class: ['btn', 'btn-sm'],
                attributes: { attr__class: ['btn', 'btn-sm'] },
            })
        )
    })
})
