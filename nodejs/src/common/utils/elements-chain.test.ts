import { chainToElements, elementsChainFromProperties, elementsToString, extractElements } from './elements-chain'

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

    it('handles empty attributes', () => {
        const element = {
            tag_name: 'div',
            attributes: {
                empty: '',
            },
        }
        const elementsString = elementsToString([element])

        expect(elementsString).toEqual('div:empty=""nth-child="0"nth-of-type="0"')
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

    it('truncates $el_text to 400 chars and attr__href to 2048 chars', () => {
        const result = extractElements([
            {
                tag_name: 'a',
                $el_text: 'a'.repeat(2050),
                attr__href: 'a'.repeat(2050),
                nth_child: 1,
                nth_of_type: 2,
                attr__class: 'btn btn-sm',
            },
        ])

        expect(result[0].text?.length).toBe(400)
        expect(result[0].href?.length).toBe(2048)
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

describe('elementsChainFromProperties()', () => {
    it('returns $elements_chain when present', () => {
        expect(elementsChainFromProperties({ $elements_chain: 'a:nth-child="1"' })).toBe('a:nth-child="1"')
    })

    it('derives the chain from a legacy $elements array', () => {
        expect(
            elementsChainFromProperties({
                $elements: [{ tag_name: 'a', $el_text: 'click', nth_child: 1, nth_of_type: 1 }],
            })
        ).toBe('a:nth-child="1"nth-of-type="1"text="click"')
    })

    it('returns an empty string when neither reserved property is present', () => {
        expect(elementsChainFromProperties({})).toBe('')
    })

    it('does not reorder the input $elements class array', () => {
        const properties = {
            $elements: [{ tag_name: 'a', attr__class: ['zeta', 'alpha'], nth_child: 1, nth_of_type: 1 }],
        }
        elementsChainFromProperties(properties)
        expect(properties.$elements[0].attr__class).toEqual(['zeta', 'alpha'])
    })

    // A malformed legacy `$elements` payload must not throw, because the transformer derives
    // the chain outside any per-event guard, where a throw crashes the ingestion worker.
    it.each([
        ['a scalar $elements', { $elements: 'not-an-array' }],
        ['a null element entry', { $elements: [null] }],
        ['a numeric $el_text', { $elements: [{ $el_text: 42 }] }],
        ['a numeric attr__class', { $elements: [{ attr__class: 42 }] }],
    ])('returns an empty string for %s', (_description, properties) => {
        expect(() => elementsChainFromProperties(properties as Record<string, any>)).not.toThrow()
        expect(elementsChainFromProperties(properties as Record<string, any>)).toBe('')
    })
})
