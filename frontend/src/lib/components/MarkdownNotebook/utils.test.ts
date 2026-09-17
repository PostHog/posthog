import { getSerializableProps } from './utils'

describe('getSerializableProps', () => {
    it('preserves a query whose nested filter carries undefined fields, stripping the undefined', () => {
        // A completed person-property filter from the DataTable carries an absent
        // label/group_type_index as `undefined`. The `query` prop has to survive that, or the
        // People table never re-queries when a filter is added.
        const result = getSerializableProps({
            query: {
                kind: 'DataTableNode',
                source: {
                    kind: 'ActorsQuery',
                    properties: [
                        { type: 'person', key: 'email', operator: 'exact', value: 'x@y.com', label: undefined },
                    ],
                },
            },
        })

        expect(result.query).toEqual({
            kind: 'DataTableNode',
            source: {
                kind: 'ActorsQuery',
                properties: [{ type: 'person', key: 'email', operator: 'exact', value: 'x@y.com' }],
            },
        })
    })

    it('keeps a fully-serializable filter (e.g. cohort) untouched', () => {
        const query = {
            kind: 'DataTableNode',
            source: {
                kind: 'ActorsQuery',
                properties: [{ type: 'cohort', key: 'id', value: 42, operator: 'in' }],
            },
        }

        expect(getSerializableProps({ query }).query).toEqual(query)
    })

    it.each([
        ['undefined', { a: undefined }, {}],
        ['function', { a: () => undefined }, {}],
    ])('omits the key entirely when the value is not serializable (%s)', (_label, attributes, expected) => {
        expect(getSerializableProps(attributes)).toEqual(expected)
    })

    it('preserves primitive, array and nested object props', () => {
        expect(
            getSerializableProps({ id: 'abc', count: 3, enabled: true, items: ['a', 'b'], nested: { x: 1 } })
        ).toEqual({ id: 'abc', count: 3, enabled: true, items: ['a', 'b'], nested: { x: 1 } })
    })

    it('strips undefined nested in an object while keeping its siblings', () => {
        expect(getSerializableProps({ nested: { keep: 'yes', drop: undefined } })).toEqual({
            nested: { keep: 'yes' },
        })
    })
})
