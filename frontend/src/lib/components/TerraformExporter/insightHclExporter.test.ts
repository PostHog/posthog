import { generateInsightHCL } from 'lib/components/TerraformExporter/insightHclExporter'

import { NodeKind } from '~/queries/schema/schema-general'
import { InsightModel } from '~/types'

// Helper to create test insights without strict query typing
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const createTestInsight = (props: Record<string, any>): Partial<InsightModel> => props as Partial<InsightModel>

describe('insightHclExporter test', () => {
    describe('sanitizes correctly', () => {
        const testCases = [
            { input: 'My Dashboard', expected: 'my_dashboard' },
            { input: 'Test-Insight-123', expected: 'test_insight_123' },
            { input: '123 Starting With Number', expected: '_123_starting_with_number' },
            { input: 'Special!@#$%Characters', expected: 'special_characters' },
            { input: '  Multiple   Spaces  ', expected: 'multiple_spaces' },
            { input: '', expected: 'insight_new' }, // Falls back to insight_${id || 'new'}
        ]

        it.each(testCases)('converts "$input" to "$expected"', ({ input, expected }) => {
            const insight = createTestInsight({
                name: input,
                query: { kind: NodeKind.TrendsQuery },
            })

            const hcl = generateInsightHCL(insight).hcl

            expect(hcl).toContain(`resource "posthog_insight" "${expected}"`)
        })
    })

    describe('escapes special characters correctly', () => {
        it('escapes special characters in strings', () => {
            const insight = createTestInsight({
                name: 'Test',
                description: 'Line 1\nLine 2\tTabbed "quoted"',
                query: { kind: NodeKind.TrendsQuery },
            })

            const hcl = generateInsightHCL(insight).hcl

            expect(hcl).toContain('Line 1\\nLine 2\\tTabbed \\"quoted\\"')
        })

        it('handles backslashes', () => {
            const insight = createTestInsight({
                name: 'Test',
                description: 'Path: C:\\Users\\test',
                query: { kind: NodeKind.TrendsQuery },
            })

            const hcl = generateInsightHCL(insight).hcl

            expect(hcl).toContain('Path: C:\\\\Users\\\\test')
        })
    })

    describe('generates valid hcl', () => {
        it('generates valid HCL for a complete insight', () => {
            const insight = createTestInsight({
                id: 123,
                short_id: 'abc123',
                name: 'My Test Insight',
                description: 'A test insight for unit testing',
                query: {
                    kind: NodeKind.TrendsQuery,
                    series: [{ event: '$pageview', kind: NodeKind.EventsNode }],
                },
                tags: ['test', 'analytics'],
                dashboards: [1, 2],
            })

            const result = generateInsightHCL(insight)
            const hcl = result.hcl

            expect(hcl).toContain('resource "posthog_insight" "my_test_insight"')
            expect(hcl).toContain('name = "My Test Insight"')
            expect(hcl).toContain('description = "A test insight for unit testing"')
            expect(hcl).toContain('query_json = jsonencode(')
            expect(hcl).toContain('tags = ["test", "analytics", "managed-by:terraform"]')
            expect(hcl).toContain('dashboard_ids = [1, 2]')

            const warnings = result.warnings

            expect(warnings).toHaveLength(1)
            expect(warnings[0]).toContain('`dashboard_ids` are hardcoded')
        })

        it('includes import block for saved insights by default', () => {
            const insight = createTestInsight({
                id: 456,
                name: 'Saved Insight',
                query: { kind: NodeKind.TrendsQuery },
            })

            const result = generateInsightHCL(insight)
            const hcl = result.hcl

            expect(hcl).toContain('import {')
            expect(hcl).toContain('to = posthog_insight.saved_insight')
            expect(hcl).toContain('id = "456"')

            const warnings = result.warnings

            expect(warnings).toHaveLength(0)
        })

        it('excludes import block for new insights', () => {
            const insight = createTestInsight({
                name: 'New Insight',
                query: { kind: NodeKind.TrendsQuery },
            })

            const result = generateInsightHCL(insight)
            const hcl = result.hcl

            expect(hcl).not.toContain('import {')

            const warnings = result.warnings

            expect(warnings).toHaveLength(0)
        })

        it('respects includeImport option', () => {
            const insight = createTestInsight({
                id: 789,
                name: 'Test Insight',
                query: { kind: NodeKind.TrendsQuery },
            })

            const hclWithImport = generateInsightHCL(insight, { includeImport: true }).hcl
            const hclWithoutImport = generateInsightHCL(insight, { includeImport: false }).hcl

            expect(hclWithImport).toContain('import {')
            expect(hclWithoutImport).not.toContain('import {')
        })

        it('uses derived_name when name is not set', () => {
            const insight = createTestInsight({
                derived_name: 'Derived Name',
                query: { kind: NodeKind.TrendsQuery },
            })

            const hcl = generateInsightHCL(insight).hcl

            expect(hcl).toContain('resource "posthog_insight" "derived_name"')
            expect(hcl).toContain('derived_name = "Derived Name"')
        })

        it('prefers name over derived_name in resource block', () => {
            const insight = createTestInsight({
                name: 'Actual Name',
                derived_name: 'Derived Name',
                query: { kind: NodeKind.TrendsQuery },
            })

            const hcl = generateInsightHCL(insight).hcl

            expect(hcl).toContain('name = "Actual Name"')
            expect(hcl).not.toContain('derived_name')
        })

        it('includes create_in_folder when set', () => {
            const insight = createTestInsight({
                name: 'Test',
                query: { kind: NodeKind.TrendsQuery },
                _create_in_folder: 'My Folder/Subfolder',
            })

            const hcl = generateInsightHCL(insight).hcl

            expect(hcl).toContain('create_in_folder = "My Folder/Subfolder"')
        })

        it('includes provider version comment', () => {
            const insight = createTestInsight({
                name: 'Test',
                query: { kind: NodeKind.TrendsQuery },
            })

            const hcl = generateInsightHCL(insight).hcl

            expect(hcl).toMatch(/# Compatible with posthog provider v\d+\.\d+/)
        })
    })

    describe('generates expected warnings', () => {
        it('warns when query is missing', () => {
            const insight = createTestInsight({
                name: 'No Query Insight',
            })

            const result = generateInsightHCL(insight)

            expect(result.warnings).toContain(
                'Missing required field: query. The insight will fail to apply without a query_json value.'
            )
        })

        it('warns when no name or derived_name is provided', () => {
            const insight = createTestInsight({
                query: { kind: NodeKind.TrendsQuery },
            })

            const result = generateInsightHCL(insight)

            expect(result.warnings).toContain(
                'No name or derived_name provided. Consider adding a name for better identification in Terraform state.'
            )
        })

        it('warns about dashboard_ids dependency', () => {
            const insight = createTestInsight({
                name: 'Test',
                query: { kind: NodeKind.TrendsQuery },
                dashboards: [1, 2, 3],
            })

            const result = generateInsightHCL(insight)

            expect(result.warnings).toContain(
                'Some `dashboard_ids` are hardcoded. After exporting, consider referencing the Terraform resource instead (for example, `posthog_dashboard.my_dashboard.id`) so the dashboard is managed alongside this configuration.'
            )
        })

        it('suppresses dashboard warnings when all dashboardIdReplacements are provided', () => {
            const insight = createTestInsight({
                name: 'Valid Insight',
                query: { kind: NodeKind.TrendsQuery },
                dashboards: [1],
            })

            const result = generateInsightHCL(insight, {
                dashboardIdReplacements: new Map([[1, 'posthog_dashboard.my_dashboard.id']]),
            })

            expect(result.hcl).toContain('dashboard_ids = [posthog_dashboard.my_dashboard.id]')
            expect(result.hcl).not.toContain('dashboard_ids = [1]')
            expect(result.warnings).toHaveLength(0)
        })

        it('supports multiple dashboard TF references', () => {
            const insight = createTestInsight({
                name: 'Multi Dashboard Insight',
                query: { kind: NodeKind.TrendsQuery },
                dashboards: [1, 2],
            })

            const result = generateInsightHCL(insight, {
                dashboardIdReplacements: new Map([
                    [1, 'posthog_dashboard.dashboard_one.id'],
                    [2, 'posthog_dashboard.dashboard_two.id'],
                ]),
            })

            expect(result.hcl).toContain(
                'dashboard_ids = [posthog_dashboard.dashboard_one.id, posthog_dashboard.dashboard_two.id]'
            )
            expect(result.warnings).toHaveLength(0)
        })

        it('replaces only mapped dashboard IDs, keeps others as hardcoded', () => {
            const insight = createTestInsight({
                name: 'Multi Dashboard Insight',
                query: { kind: NodeKind.TrendsQuery },
                dashboards: [1, 2, 3, 4],
            })

            const result = generateInsightHCL(insight, {
                dashboardIdReplacements: new Map([
                    [1, 'posthog_dashboard.dashboard_one.id'],
                    [3, 'posthog_dashboard.dashboard_three.id'],
                ]),
            })

            expect(result.hcl).toContain(
                'dashboard_ids = [posthog_dashboard.dashboard_one.id, 2, posthog_dashboard.dashboard_three.id, 4]'
            )
            // Should still warn because IDs 2 and 4 are hardcoded
            expect(result.warnings).toContain(
                'Some `dashboard_ids` are hardcoded. After exporting, consider referencing the Terraform resource instead (for example, `posthog_dashboard.my_dashboard.id`) so the dashboard is managed alongside this configuration.'
            )
        })
    })

    describe('correctly handles the managed-by:terraform tag', () => {
        it('adds managed-by:terraform tag when no tags exist', () => {
            const insight = createTestInsight({
                name: 'No Tags',
                query: { kind: NodeKind.TrendsQuery },
            })

            const hcl = generateInsightHCL(insight).hcl

            expect(hcl).toContain('tags = ["managed-by:terraform"]')
        })

        it('appends managed-by:terraform tag to existing tags', () => {
            const insight = createTestInsight({
                name: 'Has Tags',
                query: { kind: NodeKind.TrendsQuery },
                tags: ['existing', 'tags'],
            })

            const hcl = generateInsightHCL(insight).hcl

            expect(hcl).toContain('tags = ["existing", "tags", "managed-by:terraform"]')
        })

        it('does not duplicate managed-by:terraform tag if already present', () => {
            const insight = createTestInsight({
                name: 'Already Tagged',
                query: { kind: NodeKind.TrendsQuery },
                tags: ['other', 'managed-by:terraform'],
            })

            const hcl = generateInsightHCL(insight).hcl

            expect(hcl).toContain('tags = ["other", "managed-by:terraform"]')
            expect(hcl).not.toContain('tags = ["other", "managed-by:terraform", "managed-by:terraform"]')
        })
    })

    describe('query_json formatting', () => {
        it('properly formats complex nested queries', () => {
            const insight = createTestInsight({
                name: 'Complex Query',
                query: {
                    kind: NodeKind.TrendsQuery,
                    series: [
                        {
                            event: '$pageview',
                            kind: 'EventsNode',
                            properties: [
                                {
                                    key: 'url',
                                    value: 'https://example.com',
                                    operator: 'exact',
                                },
                            ],
                        },
                    ],
                    filterTestAccounts: true,
                    dateRange: {
                        date_from: '-7d',
                    },
                },
            })

            const hcl = generateInsightHCL(insight).hcl

            expect(hcl).toContain(`  query_json = jsonencode({
    "kind": "TrendsQuery",
    "series": [
      {
        "event": "$pageview",
        "kind": "EventsNode",
        "properties": [
          {
            "key": "url",
            "value": "https://example.com",
            "operator": "exact"
          }
        ]
      }
    ],
    "filterTestAccounts": true,
    "dateRange": {
      "date_from": "-7d"
    }
  })`)
        })
    })
})
