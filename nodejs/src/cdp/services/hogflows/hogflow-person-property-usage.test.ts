import { personPropertiesInBytecode, personPropertiesInTemplates } from './hogflow-person-property-usage'

describe('hogflow person property usage', () => {
    it.each([
        {
            name: 'hog format string',
            config: { inputs: { to: { value: '{person.properties.email}' } } },
            expected: ['email'],
        },
        {
            name: 'liquid template',
            config: { inputs: { body: { value: 'Hi {{ person.properties.first_name | default: "there" }}!' } } },
            expected: ['first_name'],
        },
        {
            name: 'bracket-form reference',
            config: { inputs: { body: { value: "{{ person.properties['$initial_referrer'] }}" } } },
            expected: ['$initial_referrer'],
        },
        {
            name: 'reference in mappings',
            config: { mappings: [{ inputs: { url: { value: '{person.properties.site}' } } }] },
            expected: ['site'],
        },
        {
            name: 'event property with the same shape',
            config: { inputs: { body: { value: '{event.properties.email}' } } },
            expected: [],
        },
    ])('finds the person properties a template reads: $name', ({ config, expected }) => {
        expect(personPropertiesInTemplates(config)).toEqual(expected)
    })

    it.each([
        {
            name: 'property comparison',
            bytecode: ['_H', 1, 32, 'Chrome', 32, '$browser', 32, 'properties', 32, 'person', 1, 3, 11],
            expected: ['$browser'],
        },
        {
            name: 'nested property',
            bytecode: ['_H', 1, 32, 'city', 32, 'address', 32, 'properties', 32, 'person', 1, 4],
            expected: ['address'],
        },
        {
            name: 'event property',
            bytecode: ['_H', 1, 32, 'Chrome', 32, '$browser', 32, 'properties', 1, 2, 11],
            expected: [],
        },
        {
            name: 'condition with no compiled filter',
            bytecode: undefined,
            expected: [],
        },
    ])('finds the person properties a compiled filter reads: $name', ({ bytecode, expected }) => {
        expect(personPropertiesInBytecode(bytecode)).toEqual(expected)
    })
})
