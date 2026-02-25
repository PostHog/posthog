import { generateDashboardLayoutHCL } from 'lib/components/TerraformExporter/dashboardLayoutHclExporter'

import { DashboardType } from '~/types'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const createTestDashboard = (props: Record<string, any>): Partial<DashboardType> => props as Partial<DashboardType>

describe('dashboardLayoutHclExporter test', () => {
    describe('sanitizes correctly', () => {
        const testCases = [
            { input: 'My Dashboard', expected: 'my_dashboard' },
            { input: 'Test-Dashboard-123', expected: 'test_dashboard_123' },
            { input: '123 Starting With Number', expected: '_123_starting_with_number' },
            { input: 'Special!@#$%Characters', expected: 'special_characters' },
            { input: '  Multiple   Spaces  ', expected: 'multiple_spaces' },
            { input: '', expected: 'dashboard_new' },
        ]

        it.each(testCases)('converts "$input" to "$expected"', ({ input, expected }) => {
            const dashboard = createTestDashboard({
                name: input,
                tiles: [{ id: 1, insight: { id: 1 }, color: null, layouts: {} }],
            })

            const hcl = generateDashboardLayoutHCL(dashboard, {
                dashboardTfReference: 'posthog_dashboard.test.id',
            }).hcl

            expect(hcl).toContain(`resource "posthog_dashboard_layout" "${expected}"`)
        })
    })

    describe('generates valid hcl', () => {
        it('generates valid HCL for a complete layout', () => {
            const dashboard = createTestDashboard({
                id: 1,
                name: 'My Dashboard',
                tiles: [
                    { id: 10, insight: { id: 100 }, color: null, layouts: { sm: { x: 0, y: 0, w: 6, h: 5 } } },
                    { id: 11, text: { body: 'A note' }, color: 'blue', layouts: {} },
                ],
            })

            const result = generateDashboardLayoutHCL(dashboard, {
                dashboardTfReference: 'posthog_dashboard.my_dashboard.id',
                insightIdReplacements: new Map([[100, 'posthog_insight.my_insight.id']]),
                projectId: 42,
            })

            expect(result.hcl).toContain(`resource "posthog_dashboard_layout" "my_dashboard" {
  dashboard_id = posthog_dashboard.my_dashboard.id
  tiles = [
    {
      insight_id = posthog_insight.my_insight.id
      layouts_json = jsonencode({
        "sm": {
          "x": 0,
          "y": 0,
          "w": 6,
          "h": 5
        }
      })
    },
    {
      text_body = "A note"
      color = "blue"
    },
  ]
}`)
            expect(result.hcl).toContain('import {')
            expect(result.hcl).toContain('  id = "42/1"')
            expect(result.warnings).toHaveLength(0)
        })

        it('omits layouts_json when layouts is empty', () => {
            const dashboard = createTestDashboard({
                id: 5,
                name: 'No Layouts',
                tiles: [{ id: 50, insight: { id: 500 }, color: null, layouts: {} }],
            })

            const result = generateDashboardLayoutHCL(dashboard, {
                dashboardTfReference: 'posthog_dashboard.no_layouts.id',
            })

            expect(result.hcl).toContain(`    {
      insight_id = 500
    },`)
            expect(result.hcl).not.toContain('layouts_json')
        })

        it('includes import block for saved dashboards by default', () => {
            const dashboard = createTestDashboard({
                id: 7,
                name: 'Saved',
                tiles: [{ id: 70, insight: { id: 700 }, color: null, layouts: {} }],
            })

            const result = generateDashboardLayoutHCL(dashboard, {
                dashboardTfReference: 'posthog_dashboard.saved.id',
                projectId: 42,
            })

            expect(result.hcl).toContain(`import {
  to = posthog_dashboard_layout.saved
  id = "42/7"
}`)
        })

        it('excludes import block for new dashboards', () => {
            const dashboard = createTestDashboard({
                name: 'New',
                tiles: [{ id: 90, text: { body: 'Note' }, color: null, layouts: {} }],
            })

            const result = generateDashboardLayoutHCL(dashboard)

            expect(result.hcl).not.toContain('import {')
        })

        it('respects includeImport option', () => {
            const dashboard = createTestDashboard({
                id: 9,
                name: 'Test Dashboard',
                tiles: [{ id: 91, insight: { id: 900 }, color: null, layouts: {} }],
            })

            const hclWithImport = generateDashboardLayoutHCL(dashboard, {
                dashboardTfReference: 'posthog_dashboard.test_dashboard.id',
                includeImport: true,
            }).hcl
            const hclWithoutImport = generateDashboardLayoutHCL(dashboard, {
                dashboardTfReference: 'posthog_dashboard.test_dashboard.id',
                includeImport: false,
            }).hcl

            expect(hclWithImport).toContain('import {')
            expect(hclWithoutImport).not.toContain('import {')
        })

        it('includes provider version comment', () => {
            const dashboard = createTestDashboard({
                name: 'Test',
                tiles: [{ id: 1, insight: { id: 1 }, color: null, layouts: {} }],
            })

            const hcl = generateDashboardLayoutHCL(dashboard, {
                dashboardTfReference: 'posthog_dashboard.test.id',
            }).hcl

            expect(hcl).toMatch(/# Compatible with posthog provider v\d+\.\d+/)
        })
    })

    describe('filters deleted tiles', () => {
        it('excludes deleted tiles from output', () => {
            const dashboard = createTestDashboard({
                id: 6,
                name: 'Mixed Tiles',
                tiles: [
                    { id: 60, insight: { id: 600 }, color: null, layouts: {}, deleted: false },
                    { id: 61, insight: { id: 601 }, color: null, layouts: {}, deleted: true },
                    { id: 62, text: { body: 'Active' }, color: null, layouts: {} },
                ],
            })

            const result = generateDashboardLayoutHCL(dashboard, {
                dashboardTfReference: 'posthog_dashboard.mixed_tiles.id',
            })

            expect(result.hcl).toContain(`  tiles = [
    {
      insight_id = 600
    },
    {
      text_body = "Active"
    },
  ]`)
        })
    })

    describe('generates expected warnings', () => {
        it('warns when dashboard_id is hardcoded', () => {
            const dashboard = createTestDashboard({
                id: 10,
                name: 'Hardcoded',
                tiles: [{ id: 100, insight: { id: 1000 }, color: null, layouts: {} }],
            })

            const result = generateDashboardLayoutHCL(dashboard)

            expect(result.warnings).toHaveLength(1)
            expect(result.warnings[0]).toContain('`dashboard_id` is hardcoded')
        })

        it('does not warn when dashboard TF reference is provided', () => {
            const dashboard = createTestDashboard({
                id: 11,
                name: 'Referenced',
                tiles: [{ id: 110, insight: { id: 1100 }, color: null, layouts: {} }],
            })

            const result = generateDashboardLayoutHCL(dashboard, {
                dashboardTfReference: 'posthog_dashboard.referenced.id',
            })

            expect(result.warnings).toHaveLength(0)
        })

        it('falls back to hardcoded insight_id when no replacement exists', () => {
            const dashboard = createTestDashboard({
                id: 12,
                name: 'Partial Refs',
                tiles: [{ id: 120, insight: { id: 1200 }, color: null, layouts: {} }],
            })

            const result = generateDashboardLayoutHCL(dashboard, {
                dashboardTfReference: 'posthog_dashboard.partial_refs.id',
                insightIdReplacements: new Map(),
            })

            expect(result.hcl).toContain(`    {
      insight_id = 1200
    },`)
        })
    })
})
