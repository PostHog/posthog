import { chainToElements, elementsToString } from '../../src/utils/db/utils'

test('elementsToString and chainToElements', () => {
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

    const elements = chainToElements(elementsString)
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
