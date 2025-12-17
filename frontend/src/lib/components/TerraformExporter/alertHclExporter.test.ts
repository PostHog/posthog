import { generateAlertHCL } from 'lib/components/TerraformExporter/alertHclExporter'

import { AlertType } from '~/lib/components/Alerts/types'

const createTestAlert = (props: Record<string, unknown>): Partial<AlertType> => props as Partial<AlertType>

describe('alertHclExporter test', () => {
    describe('sanitizes correctly', () => {
        const testCases = [
            { input: 'My Alert', expected: 'my_alert' },
            { input: 'Test-Alert-123', expected: 'test_alert_123' },
            { input: '123 Starting With Number', expected: '_123_starting_with_number' },
            { input: 'Special!@#$%Characters', expected: 'special_characters' },
            { input: '  Multiple   Spaces  ', expected: 'multiple_spaces' },
            { input: '', expected: 'alert_new' },
        ]

        it.each(testCases)('converts "$input" to "$expected"', ({ input, expected }) => {
            const alert = createTestAlert({
                name: input,
                condition: { type: 'absolute' },
                threshold: { configuration: { type: 'percentage' } },
            })

            const hcl = generateAlertHCL(alert).hcl

            expect(hcl).toContain(`resource "posthog_alert" "${expected}"`)
        })
    })

    describe('generates valid hcl', () => {
        it('generates valid HCL for a complete alert', () => {
            const alert = createTestAlert({
                id: 'alert-123',
                name: 'My Test Alert',
                enabled: true,
                calculation_interval: 'daily',
                condition: { type: 'absolute_value' },
                threshold: { configuration: { type: 'percentage', bounds: { lower: 5, upper: 15 } } },
                config: { type: 'TrendsAlertConfig', series_index: 0, check_ongoing_interval: true },
                skip_weekend: true,
                insight: { id: 456 },
            })

            const result = generateAlertHCL(alert)
            const hcl = result.hcl

            expect(hcl).toContain('resource "posthog_alert" "my_test_alert"')
            expect(hcl).toContain('name = "My Test Alert"')
            expect(hcl).toContain('enabled = true')
            expect(hcl).toContain('calculation_interval = "daily"')
            expect(hcl).toContain('condition_type = "absolute_value"')
            expect(hcl).toContain('threshold_type = "percentage"')
            expect(hcl).toContain('threshold_lower = 5')
            expect(hcl).toContain('threshold_upper = 15')
            expect(hcl).toContain('series_index = 0')
            expect(hcl).toContain('check_ongoing_interval = true')
            expect(hcl).toContain('skip_weekend = true')
            expect(hcl).toContain('insight = 456')

            // Should warn about hardcoded insight id
            expect(result.warnings).toContain(
                '`insight id` is hardcoded. Consider referencing the Terraform resource instead (e.g., `posthog_insight.my_insight.id`).'
            )
        })

        it('includes import block for saved alerts by default', () => {
            const alert = createTestAlert({
                id: 'alert-456',
                name: 'Saved Alert',
                condition: { type: 'absolute' },
                threshold: { configuration: { type: 'percentage' } },
            })

            const result = generateAlertHCL(alert)
            const hcl = result.hcl

            expect(hcl).toContain('import {')
            expect(hcl).toContain('to = posthog_alert.saved_alert')
            expect(hcl).toContain('id = "alert-456"')
        })

        it('excludes import block for new alerts', () => {
            const alert = createTestAlert({
                name: 'New Alert',
                condition: { type: 'absolute' },
                threshold: { configuration: { type: 'percentage' } },
            })

            const result = generateAlertHCL(alert)
            const hcl = result.hcl

            expect(hcl).not.toContain('import {')
        })

        it('uses TF reference for insight id when provided', () => {
            const alert = createTestAlert({
                id: 'alert-789',
                name: 'Test Alert',
                condition: { type: 'absolute' },
                threshold: { configuration: { type: 'percentage' } },
                insight: { id: 456 },
            })

            const result = generateAlertHCL(alert, { insightTfReference: 'posthog_insight.my_insight.id' })
            const hcl = result.hcl

            expect(hcl).toContain('insight = posthog_insight.my_insight.id')
            expect(hcl).not.toContain('insight = 456')

            // Should not warn about hardcoded insight id when using TF reference
            expect(result.warnings).not.toContain(
                '`insight id` is hardcoded. Consider referencing the Terraform resource instead (e.g., `posthog_insight.my_insight.id`).'
            )
        })

        it('includes provider version comment', () => {
            const alert = createTestAlert({
                name: 'Test',
                condition: { type: 'absolute' },
                threshold: { configuration: { type: 'percentage' } },
            })

            const hcl = generateAlertHCL(alert).hcl

            expect(hcl).toMatch(/# Compatible with posthog provider v\d+\.\d+/)
        })
    })

    describe('generates expected warnings', () => {
        it('warns when name is missing', () => {
            const alert = createTestAlert({
                condition: { type: 'absolute' },
                threshold: { configuration: { type: 'percentage' } },
            })

            const result = generateAlertHCL(alert)

            expect(result.warnings).toContain(
                'No name provided. Consider adding a name for better identification in Terraform state.'
            )
        })

        it('warns when threshold_type is missing', () => {
            const alert = createTestAlert({
                name: 'Test',
                condition: { type: 'absolute_value' },
            })

            const result = generateAlertHCL(alert)

            expect(result.warnings).toContain(
                'Missing required field: threshold_type. The alert will fail to apply without this value.'
            )
        })

        it('warns about subscribed_users', () => {
            const alert = createTestAlert({
                name: 'Test',
                condition: { type: 'absolute_value' },
                threshold: { configuration: { type: 'percentage' } },
                subscribed_users: [
                    { id: 1, first_name: 'John', email: 'john@example.com' },
                    { id: 2, first_name: '', email: 'jane@example.com' },
                ],
            })

            const result = generateAlertHCL(alert)

            expect(result.warnings).toContain(
                '`subscribed_users` contains internal user IDs. These IDs are specific to this PostHog instance and will need to be updated if deploying to a different environment.'
            )
        })
    })

    describe('subscribed_users field', () => {
        it('exports subscribed_users as array of IDs', () => {
            const alert = createTestAlert({
                name: 'Test',
                condition: { type: 'absolute_value' },
                threshold: { configuration: { type: 'percentage' } },
                subscribed_users: [
                    { id: 1, first_name: 'John', email: 'john@example.com' },
                    { id: 2, first_name: 'Jane', email: 'jane@example.com' },
                ],
            })

            const hcl = generateAlertHCL(alert).hcl

            expect(hcl).toContain('subscribed_users = [1, 2]')
        })

        it('also includes subscribed_users when empty', () => {
            const alert = createTestAlert({
                name: 'Test',
                condition: { type: 'absolute_value' },
                threshold: { configuration: { type: 'percentage' } },
                subscribed_users: [],
            })

            const hcl = generateAlertHCL(alert).hcl

            expect(hcl).toContain('subscribed_users = []')
        })
    })

    describe('threshold bounds', () => {
        it('includes only threshold_lower when upper is not set', () => {
            const alert = createTestAlert({
                name: 'Lower Only',
                condition: { type: 'absolute_value' },
                threshold: { configuration: { type: 'absolute', bounds: { lower: 10 } } },
            })

            const hcl = generateAlertHCL(alert).hcl

            expect(hcl).toContain('threshold_lower = 10')
            expect(hcl).not.toContain('threshold_upper')
        })

        it('includes only threshold_upper when lower is not set', () => {
            const alert = createTestAlert({
                name: 'Upper Only',
                condition: { type: 'absolute_value' },
                threshold: { configuration: { type: 'absolute', bounds: { upper: 100 } } },
            })

            const hcl = generateAlertHCL(alert).hcl

            expect(hcl).toContain('threshold_upper = 100')
            expect(hcl).not.toContain('threshold_lower')
        })

        it('excludes both bounds when not set', () => {
            const alert = createTestAlert({
                name: 'No Bounds',
                condition: { type: 'absolute_value' },
                threshold: { configuration: { type: 'percentage' } },
            })

            const hcl = generateAlertHCL(alert).hcl

            expect(hcl).not.toContain('threshold_lower')
            expect(hcl).not.toContain('threshold_upper')
        })
    })

    describe('config fields', () => {
        it('includes series_index when set to 0', () => {
            const alert = createTestAlert({
                name: 'Series Zero',
                condition: { type: 'absolute_value' },
                threshold: { configuration: { type: 'percentage' } },
                config: { type: 'TrendsAlertConfig', series_index: 0 },
            })

            const hcl = generateAlertHCL(alert).hcl

            expect(hcl).toContain('series_index = 0')
        })

        it('includes check_ongoing_interval when false', () => {
            const alert = createTestAlert({
                name: 'No Ongoing Check',
                condition: { type: 'absolute_value' },
                threshold: { configuration: { type: 'percentage' } },
                config: { type: 'TrendsAlertConfig', series_index: 1, check_ongoing_interval: false },
            })

            const hcl = generateAlertHCL(alert).hcl

            expect(hcl).toContain('series_index = 1')
            expect(hcl).toContain('check_ongoing_interval = false')
        })

        it('excludes check_ongoing_interval when undefined', () => {
            const alert = createTestAlert({
                name: 'No Ongoing Check Config',
                condition: { type: 'absolute_value' },
                threshold: { configuration: { type: 'percentage' } },
                config: { type: 'TrendsAlertConfig', series_index: 1 },
            })

            const hcl = generateAlertHCL(alert).hcl

            expect(hcl).toContain('series_index = 1')
            expect(hcl).not.toContain('check_ongoing_interval')
        })
    })
})
