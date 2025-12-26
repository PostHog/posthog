import {
    generateHogFunctionHCL,
    stripFiltersServerFields,
    stripInputsServerFields,
    stripMappingsServerFields,
} from 'lib/components/TerraformExporter/hogFunctionHclExporter'

import { CyclotronJobFiltersType, CyclotronJobInputType, HogFunctionMappingType, HogFunctionType } from '~/types'

const createTestHogFunction = (props: Record<string, unknown>): Partial<HogFunctionType> =>
    props as Partial<HogFunctionType>

describe('hogFunctionHclExporter test', () => {
    describe('sanitizes correctly', () => {
        const testCases = [
            { input: 'My Function', expected: 'my_function' },
            { input: 'Test-Function-123', expected: 'test_function_123' },
            { input: '123 Starting With Number', expected: '_123_starting_with_number' },
            { input: 'Special!@#$%Characters', expected: 'special_characters' },
            { input: '  Multiple   Spaces  ', expected: 'multiple_spaces' },
            { input: '', expected: 'hog_function_new' },
        ]

        it.each(testCases)('converts "$input" to "$expected"', ({ input, expected }) => {
            const hogFunction = createTestHogFunction({
                name: input,
                type: 'internal_destination',
            })

            const hcl = generateHogFunctionHCL(hogFunction).hcl

            expect(hcl).toContain(`resource "posthog_hog_function" "${expected}"`)
        })
    })

    describe('generates valid hcl', () => {
        it('generates valid HCL for a complete hog function', () => {
            const hogFunction = createTestHogFunction({
                id: 'func-123',
                name: 'My Test Function',
                description: 'A test hog function',
                type: 'internal_destination',
                enabled: true,
                hog: 'print("Hello World")',
                inputs: { channel: { value: '#general' } },
                filters: {
                    events: [{ id: '$insight_alert_firing', type: 'events' }],
                    properties: [{ key: 'alert_id', value: 'alert-456', operator: 'exact' }],
                },
                icon_url: 'https://example.com/icon.png',
            })

            const result = generateHogFunctionHCL(hogFunction)
            const hcl = result.hcl

            expect(hcl).toContain('resource "posthog_hog_function" "my_test_function"')
            expect(hcl).toContain('name = "My Test Function"')
            expect(hcl).toContain('description = "A test hog function"')
            expect(hcl).toContain('type = "internal_destination"')
            expect(hcl).toContain('enabled = true')
            expect(hcl).toContain('hog = "print(\\"Hello World\\")"')
            expect(hcl).toContain('icon_url = "https://example.com/icon.png"')

            expect(hcl).toContain(`inputs_json = jsonencode({
    "channel": {
      "value": "#general"
    }
  })`)

            expect(hcl).toContain(`filters_json = jsonencode({
    "events": [
      {
        "id": "$insight_alert_firing",
        "type": "events"
      }
    ],
    "properties": [
      {
        "key": "alert_id",
        "value": "alert-456",
        "operator": "exact"
      }
    ]
  })`)

            expect(result.warnings).toHaveLength(0)
        })

        it('includes import block for saved hog functions by default', () => {
            const hogFunction = createTestHogFunction({
                id: 'func-456',
                name: 'Saved Function',
                type: 'internal_destination',
            })

            const result = generateHogFunctionHCL(hogFunction)
            const hcl = result.hcl

            expect(hcl).toContain('import {')
            expect(hcl).toContain('to = posthog_hog_function.saved_function')
            expect(hcl).toContain('id = "func-456"')
        })

        it('excludes import block for new hog functions', () => {
            const hogFunction = createTestHogFunction({
                name: 'New Function',
                type: 'internal_destination',
            })

            const result = generateHogFunctionHCL(hogFunction)
            const hcl = result.hcl

            expect(hcl).not.toContain('import {')
        })

        it('replaces hardcoded alert_id with TF reference when provided', () => {
            const hogFunction = createTestHogFunction({
                id: 'func-789',
                name: 'Test Function',
                type: 'internal_destination',
                filters: {
                    events: [{ id: '$insight_alert_firing', type: 'events' }],
                    properties: [
                        { key: 'alert_id', value: 'alert-456', operator: 'exact' },
                        { key: 'alert_id2', value: 'alert-678', operator: 'exact' },
                    ],
                },
            })

            const result = generateHogFunctionHCL(hogFunction, {
                alertIdReplacements: new Map([['alert-456', 'posthog_alert.my_alert.id']]),
            })
            const hcl = result.hcl

            expect(hcl).toContain('posthog_alert.my_alert.id')
            expect(hcl).not.toContain('"alert-456"')
            expect(hcl).toContain('"alert-678"')
        })

        it('includes provider version comment', () => {
            const hogFunction = createTestHogFunction({
                name: 'Test',
                type: 'internal_destination',
            })

            const hcl = generateHogFunctionHCL(hogFunction).hcl

            expect(hcl).toMatch(/# Compatible with posthog provider v\d+\.\d+/)
        })

        it('includes execution_order when provided', () => {
            const hogFunction = createTestHogFunction({
                name: 'Ordered Function',
                type: 'transformation',
                execution_order: 5,
            })

            const hcl = generateHogFunctionHCL(hogFunction).hcl

            expect(hcl).toContain('execution_order = 5')
        })

        it('includes execution_order when zero', () => {
            const hogFunction = createTestHogFunction({
                name: 'Zero Order Function',
                type: 'transformation',
                execution_order: 0,
            })

            const hcl = generateHogFunctionHCL(hogFunction).hcl

            expect(hcl).toContain('execution_order = 0')
        })

        it('includes mappings_json when provided', () => {
            const hogFunction = createTestHogFunction({
                name: 'Mapped Function',
                type: 'destination',
                mappings: [
                    { name: 'Track Event', inputs: { event: { value: '$pageview' } } },
                    { name: 'Identify User', inputs: { userId: { value: '{person.id}' } } },
                ],
            })

            const hcl = generateHogFunctionHCL(hogFunction).hcl

            expect(hcl).toContain(`mappings_json = jsonencode([
    {
      "name": "Track Event",
      "inputs": {
        "event": {
          "value": "$pageview"
        }
      }
    },
    {
      "name": "Identify User",
      "inputs": {
        "userId": {
          "value": "{person.id}"
        }
      }
    }
  ])`)
        })

        it('excludes mappings_json when empty array', () => {
            const hogFunction = createTestHogFunction({
                name: 'No Mappings',
                type: 'destination',
                mappings: [],
            })

            const hcl = generateHogFunctionHCL(hogFunction).hcl

            expect(hcl).not.toContain('mappings_json')
        })

        it('includes masking_json when provided', () => {
            const hogFunction = createTestHogFunction({
                name: 'Masked Function',
                type: 'destination',
                masking: {
                    hash: ['email', 'phone'],
                    ttl: 3600,
                },
            })

            const hcl = generateHogFunctionHCL(hogFunction).hcl

            expect(hcl).toContain(`masking_json = jsonencode({
    "hash": [
      "email",
      "phone"
    ],
    "ttl": 3600
  })`)
        })

        it('excludes masking_json when empty object', () => {
            const hogFunction = createTestHogFunction({
                name: 'No Masking',
                type: 'destination',
                masking: {},
            })

            const hcl = generateHogFunctionHCL(hogFunction).hcl

            expect(hcl).not.toContain('masking_json')
        })

        it('includes template_id when template is provided', () => {
            const hogFunction = createTestHogFunction({
                name: 'Templated Function',
                type: 'destination',
                template: {
                    id: 'template-slack-webhook',
                    name: 'Slack Webhook',
                    status: 'stable',
                },
            })

            const hcl = generateHogFunctionHCL(hogFunction).hcl

            expect(hcl).toContain('template_id = "template-slack-webhook"')
        })

        it('excludes template_id when template has no id', () => {
            const hogFunction = createTestHogFunction({
                name: 'Function Without Template',
                type: 'destination',
                template: {
                    name: 'Incomplete Template',
                },
            })

            const hcl = generateHogFunctionHCL(hogFunction).hcl

            expect(hcl).not.toContain('template_id =')
        })

        it('generates valid HCL when inputs contain null values', () => {
            const hogFunction = createTestHogFunction({
                id: 'func-with-nulls',
                name: 'Slack Function With Nulls',
                type: 'internal_destination',
                inputs: {
                    channel: { value: '#alerts', bytecode: ['_H', 1], order: 0 },
                    username: null,
                    icon_emoji: null,
                    blocks: { value: '[]', bytecode: ['_H', 2], order: 1 },
                },
            })

            const result = generateHogFunctionHCL(hogFunction)

            expect(result.warnings).toHaveLength(0)
            expect(result.hcl).toContain('inputs_json = jsonencode')
            expect(result.hcl).toContain('"channel"')
            expect(result.hcl).toContain('"username": null')
            expect(result.hcl).toContain('"icon_emoji": null')
            expect(result.hcl).not.toContain('bytecode')
        })
    })

    describe('generates expected warnings', () => {
        it('warns when name is missing', () => {
            const hogFunction = createTestHogFunction({
                type: 'internal_destination',
            })

            const result = generateHogFunctionHCL(hogFunction)

            expect(result.warnings).toContain(
                'No name provided. Consider adding a name for better identification in Terraform state.'
            )
        })

        it('warns about secret inputs', () => {
            const hogFunction = createTestHogFunction({
                name: 'Test',
                type: 'internal_destination',
                inputs: {
                    api_key: { value: 'secret-key', secret: true },
                    channel: { value: '#general' },
                },
            })

            const result = generateHogFunctionHCL(hogFunction)

            expect(result.warnings).toContain(
                'Secret inputs (api_key) in the export, please be careful when handling this file!'
            )
        })

        it('warns about multiple secret inputs', () => {
            const hogFunction = createTestHogFunction({
                name: 'Test',
                type: 'internal_destination',
                inputs: {
                    api_key: { value: 'secret-key', secret: true },
                    webhook_secret: { value: 'webhook-secret', secret: true },
                    channel: { value: '#general' },
                },
            })

            const result = generateHogFunctionHCL(hogFunction)

            expect(result.warnings).toContain(
                'Secret inputs (api_key, webhook_secret) in the export, please be careful when handling this file!'
            )
        })
    })

    describe('strips server-computed fields', () => {
        describe('stripInputsServerFields', () => {
            it('removes bytecode and order from inputs', () => {
                const inputs: Record<string, CyclotronJobInputType> = {
                    channel: { value: '#general', bytecode: ['_H', 1, 32], order: 0 },
                    message: { value: 'Hello', bytecode: ['_H', 1, 33], order: 1 },
                }

                const result = stripInputsServerFields(inputs)

                expect(result).toEqual({
                    channel: { value: '#general' },
                    message: { value: 'Hello' },
                })
            })

            it('preserves other fields like secret and templating', () => {
                const inputs: Record<string, CyclotronJobInputType> = {
                    api_key: { value: 'secret', secret: true, bytecode: ['_H'], order: 0 },
                    template: { value: '{event.name}', templating: 'hog', bytecode: ['_H', 2], order: 1 },
                }

                const result = stripInputsServerFields(inputs)

                expect(result).toEqual({
                    api_key: { value: 'secret', secret: true },
                    template: { value: '{event.name}', templating: 'hog' },
                })
            })

            it('returns null/undefined unchanged', () => {
                expect(stripInputsServerFields(null)).toBeNull()
                expect(stripInputsServerFields(undefined)).toBeUndefined()
            })

            it('handles null input values gracefully', () => {
                const inputs: Record<string, CyclotronJobInputType | null> = {
                    channel: { value: '#general', bytecode: ['_H', 1, 32], order: 0 },
                    username: null,
                    icon_emoji: null,
                }

                const result = stripInputsServerFields(inputs)

                expect(result).toEqual({
                    channel: { value: '#general' },
                    username: null,
                    icon_emoji: null,
                })
            })
        })

        describe('stripFiltersServerFields', () => {
            it('removes bytecode from filters', () => {
                const filters = {
                    events: [{ id: '$pageview', type: 'events' }],
                    properties: [{ key: 'url', value: '/home', type: 'event', operator: 'exact' }],
                    bytecode: ['_H', 1, 2, 3],
                } as CyclotronJobFiltersType

                const result = stripFiltersServerFields(filters)

                expect(result).toEqual({
                    events: [{ id: '$pageview', type: 'events' }],
                    properties: [{ key: 'url', value: '/home', type: 'event', operator: 'exact' }],
                })
                expect(result).not.toHaveProperty('bytecode')
            })

            it('returns null/undefined unchanged', () => {
                expect(stripFiltersServerFields(null)).toBeNull()
                expect(stripFiltersServerFields(undefined)).toBeUndefined()
            })
        })

        describe('stripMappingsServerFields', () => {
            it('strips inputs and filters within each mapping', () => {
                const mappings = [
                    {
                        name: 'Track Event',
                        inputs: {
                            event: { value: '$pageview', bytecode: ['_H', 1], order: 0 },
                        },
                        filters: {
                            events: [{ id: 'custom_event', type: 'events' }],
                            bytecode: ['_H', 2, 3],
                        },
                    },
                    {
                        name: 'Identify',
                        inputs: {
                            userId: { value: '{person.id}', bytecode: ['_H', 4], order: 0 },
                        },
                        filters: null,
                    },
                ] as HogFunctionMappingType[]

                const result = stripMappingsServerFields(mappings)

                expect(result).toEqual([
                    {
                        name: 'Track Event',
                        inputs: {
                            event: { value: '$pageview' },
                        },
                        filters: {
                            events: [{ id: 'custom_event', type: 'events' }],
                        },
                    },
                    {
                        name: 'Identify',
                        inputs: {
                            userId: { value: '{person.id}' },
                        },
                        filters: null,
                    },
                ])
            })

            it('returns null/undefined unchanged', () => {
                expect(stripMappingsServerFields(null)).toBeNull()
                expect(stripMappingsServerFields(undefined)).toBeUndefined()
            })
        })

        it('excludes bytecode and order from generated HCL', () => {
            const hogFunction = createTestHogFunction({
                name: 'Function With Server Fields',
                type: 'destination',
                inputs: {
                    channel: { value: '#general', bytecode: ['_H', 1, 32], order: 0 },
                },
                filters: {
                    events: [{ id: '$pageview' }],
                    bytecode: ['_H', 1, 2, 3],
                },
                mappings: [
                    {
                        name: 'Mapping',
                        inputs: { event: { value: 'test', bytecode: ['_H'], order: 0 } },
                        filters: { events: [], bytecode: ['_H', 5] },
                    },
                ],
            })

            const hcl = generateHogFunctionHCL(hogFunction).hcl

            expect(hcl).not.toContain('bytecode')
            expect(hcl).not.toContain('"order"')
            expect(hcl).toContain('"value": "#general"')
            expect(hcl).toContain('"value": "test"')
        })
    })
})
