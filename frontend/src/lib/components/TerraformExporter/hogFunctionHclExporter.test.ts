import { generateHogFunctionHCL } from 'lib/components/TerraformExporter/hogFunctionHclExporter'

import { HogFunctionType } from '~/types'

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
                inputs_schema: [{ key: 'channel', type: 'string', label: 'Channel' }],
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

            expect(hcl).toContain(`inputs_schema_json = jsonencode([
    {
      "key": "channel",
      "type": "string",
      "label": "Channel"
    }
  ])`)

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
                    properties: [{ key: 'alert_id', value: 'alert-456', operator: 'exact' }],
                },
            })

            const result = generateHogFunctionHCL(hogFunction, {
                alertTfReference: 'posthog_alert.my_alert.id',
                alertId: 'alert-456',
            })
            const hcl = result.hcl

            expect(hcl).toContain('posthog_alert.my_alert.id')
            expect(hcl).not.toContain('"alert-456"')
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
                'Secret inputs (api_key) cannot be exported. You will need to configure these manually after import.'
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
                'Secret inputs (api_key, webhook_secret) cannot be exported. You will need to configure these manually after import.'
            )
        })
    })
})
