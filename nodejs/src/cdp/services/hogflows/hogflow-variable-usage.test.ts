import { findMissingVariableReferences } from './hogflow-variable-usage'

describe('findMissingVariableReferences', () => {
    it.each([
        {
            name: 'hog format string referencing an unset variable',
            config: { inputs: { subject: { value: 'Your code: {variables.coupon}' } } },
            variables: {},
            expected: ['coupon'],
        },
        {
            name: 'a variable only a send through the API reads, in a workflow run',
            config: {
                inputs: {
                    body: {
                        value: '{% if event.event == &quot;$transactional_email&quot; or variables.city != nil %}{{ variables.city }}{% else %}{{ person.properties.city }}{% endif %}{{ variables.plan }}',
                    },
                },
            },
            variables: {},
            expected: ['plan'],
        },
        {
            name: 'a variable only a send through the API reads, in one',
            config: {
                inputs: {
                    body: {
                        value: '{% if event.event == &quot;$transactional_email&quot; or variables.city != nil %}{{ variables.city }}{% else %}{{ person.properties.city }}{% endif %}{{ variables.plan }}',
                    },
                },
            },
            variables: {},
            event: '$transactional_email',
            expected: ['city', 'plan'],
        },
        {
            name: 'liquid template referencing an unset variable',
            config: { inputs: { body: { value: 'Hi {{ variables.first_name }}!' } } },
            variables: {},
            expected: ['first_name'],
        },
        {
            name: 'bracket-form reference',
            config: { inputs: { body: { value: "{{ variables['my-var'] }}" } } },
            variables: {},
            expected: ['my-var'],
        },
        {
            name: 'bracket-form reference with whitespace',
            config: { inputs: { body: { value: '{{ variables [ "spaced" ] }}' } } },
            variables: {},
            expected: ['spaced'],
        },
        {
            name: 'reference nested inside object and array input values',
            config: {
                inputs: {
                    payload: { value: { items: [{ text: '{variables.deep}' }] } },
                },
            },
            variables: {},
            expected: ['deep'],
        },
        {
            name: 'references in mappings',
            config: { mappings: [{ inputs: { url: { value: '{variables.link}' } } }] },
            variables: {},
            expected: ['link'],
        },
        {
            name: 'variable set on the run',
            config: { inputs: { subject: { value: '{variables.coupon}' } } },
            variables: { coupon: 'SAVE10' },
            expected: [],
        },
        {
            name: 'variable declared with a null default is not missing',
            config: { inputs: { subject: { value: '{variables.coupon}' } } },
            variables: { coupon: null },
            expected: [],
        },
        {
            name: 'no variable references',
            config: { inputs: { subject: { value: 'Hello {person.properties.name}' } } },
            variables: {},
            expected: [],
        },
        {
            name: 'compiled bytecode alongside the value does not produce false positives',
            config: {
                inputs: {
                    subject: {
                        value: 'plain text',
                        bytecode: ['_H', 1, 32, 'variables', 32, 'coupon', 1, 2],
                    },
                },
            },
            variables: {},
            expected: [],
        },
        {
            name: 'bytecode is not scanned even when a constant embeds matching text',
            config: {
                inputs: {
                    subject: {
                        value: 'plain text',
                        // A template string carried verbatim as a bytecode constant: the executor
                        // renders from `value`, so this must not be reported
                        bytecode: ['_H', 1, 32, 'Your code: {{ variables.ghost }}'],
                        transpiled: 'return `${variables.spectre}`',
                    },
                },
            },
            variables: {},
            expected: [],
        },
        {
            name: 'multiple missing references come back sorted and unique',
            config: {
                inputs: {
                    a: { value: '{variables.zeta} and {variables.alpha} and {variables.zeta}' },
                },
            },
            variables: {},
            expected: ['alpha', 'zeta'],
        },
        {
            name: 'undefined variables map treats every reference as missing',
            config: { inputs: { subject: { value: '{variables.coupon}' } } },
            variables: undefined,
            expected: ['coupon'],
        },
    ])('$name', ({ config, variables, event, expected }) => {
        expect(findMissingVariableReferences(config, variables, event)).toEqual(expected)
    })
})
