import { SegmentInputField, coerceFields } from './coerce-inputs'

describe('coerceFields', () => {
    const fields: Record<string, SegmentInputField> = {
        value: { type: 'number' },
        num_items: { type: 'integer' },
        order_id: { type: 'string' },
        guest: { type: 'boolean' },
        email: { type: 'string', multiple: true },
        custom_data: {
            type: 'object',
            properties: { value: { type: 'number' }, currency: { type: 'string' }, mobile: { type: 'boolean' } },
        },
        contents: {
            type: 'object',
            multiple: true,
            properties: { quantity: { type: 'integer' } },
        },
        event_properties: { type: 'object' },
    }

    it.each([
        ['renders numbers as numbers', { value: '42.5' }, { value: 42.5 }],
        ['renders integers as integers', { num_items: '3' }, { num_items: 3 }],
        ['leaves a string field alone', { order_id: '00012' }, { order_id: '00012' }],
        ['renders booleans as booleans', { guest: 'false' }, { guest: false }],
        ['coerces a nested boolean', { custom_data: { mobile: 'true' } }, { custom_data: { mobile: true } }],
        ['wraps a scalar into a declared array', { email: 'a@example.com' }, { email: ['a@example.com'] }],
        ['leaves a declared array alone', { email: ['a@example.com'] }, { email: ['a@example.com'] }],
        ['coerces inside a declared object', { custom_data: { value: '9' } }, { custom_data: { value: 9 } }],
        ['coerces inside an array of objects', { contents: { quantity: '2' } }, { contents: [{ quantity: 2 }] }],
        // A hog template that resolves to nothing must not become 0, and a value that is not a
        // number must reach the destination as the customer wrote it rather than as NaN.
        ['leaves an empty string alone', { value: '' }, { value: '' }],
        ['leaves an unparseable number alone', { value: 'lots' }, { value: 'lots' }],
        ['leaves a fractional integer alone', { num_items: '2.5' }, { num_items: '2.5' }],
        ['leaves a word that is not a boolean alone', { guest: 'yes' }, { guest: 'yes' }],
        ['leaves an empty string out of a declared array', { email: '' }, { email: '' }],
        ['leaves null alone', { value: null }, { value: null }],
        // The same object carries the destination settings and any key a customer added to a
        // dictionary input, so nothing the schema does not declare may be touched.
        [
            'keeps undeclared keys',
            { debug_mode: true, custom_data: { mine: '7' } },
            { debug_mode: true, custom_data: { mine: '7' } },
        ],
        ['leaves a free-form object alone', { event_properties: { price: '5' } }, { event_properties: { price: '5' } }],
    ])('%s', (_name, input, expected) => {
        expect(coerceFields(input, fields)).toEqual(expected)
    })

    it('does not mutate the inputs it was given', () => {
        const inputs = { custom_data: { value: '9' } }
        coerceFields(inputs, fields)
        expect(inputs).toEqual({ custom_data: { value: '9' } })
    })
})
