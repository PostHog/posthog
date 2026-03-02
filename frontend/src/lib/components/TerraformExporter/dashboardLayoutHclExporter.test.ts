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
            { input: '', expected: 'dashboard_layout_new' },
        ]

        it.each(testCases)('converts "$input" to "$expected"', ({ input, expected }) => {
            const dashboard = createTestDashboard({
                name: input,
                tiles: [{ id: 1, insight: { id: 1 }, color: null, layouts: {} }],
            })

            const hcl = generateDashboardLayoutHCL(dashboard, {
                dashboardTfReference: 'posthog_dashboard.test.id',
                insightIdReplacements: new Map(),
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

            expect(result.hcl).toContain(`import {
  to = posthog_dashboard_layout.my_dashboard
  id = "42/1"
}

resource "posthog_dashboard_layout" "my_dashboard" {
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
                insightIdReplacements: new Map(),
            })

            expect(result.hcl).toContain(`{
      insight_id = 500
    },`)
            expect(result.hcl).not.toContain('layouts_json')
        })

        it('excludes import block for new dashboards', () => {
            const dashboard = createTestDashboard({
                name: 'New',
                tiles: [{ id: 90, text: { body: 'Note' }, color: null, layouts: {} }],
            })

            const result = generateDashboardLayoutHCL(dashboard, {
                dashboardTfReference: 'posthog_dashboard.new.id',
                insightIdReplacements: new Map(),
            })

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
                insightIdReplacements: new Map(),
                includeImport: true,
            }).hcl
            const hclWithoutImport = generateDashboardLayoutHCL(dashboard, {
                dashboardTfReference: 'posthog_dashboard.test_dashboard.id',
                insightIdReplacements: new Map(),
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
                insightIdReplacements: new Map(),
            }).hcl

            expect(hcl).toMatch(/# Compatible with posthog provider v\d+\.\d+/)
        })
    })

    describe('filters unusable tiles', () => {
        it('excludes tiles with neither insight nor text', () => {
            const dashboard = createTestDashboard({
                id: 7,
                name: 'Empty Tiles',
                tiles: [
                    { id: 70, insight: { id: 700 }, color: null, layouts: {} },
                    { id: 71, color: 'blue', layouts: {} },
                    { id: 72, text: { body: 'Keep me' }, color: null, layouts: {} },
                ],
            })

            const result = generateDashboardLayoutHCL(dashboard, {
                dashboardTfReference: 'posthog_dashboard.empty_tiles.id',
                insightIdReplacements: new Map(),
            })

            expect(result.hcl).toContain(`resource "posthog_dashboard_layout" "empty_tiles" {
  dashboard_id = posthog_dashboard.empty_tiles.id
  tiles = [
    {
      insight_id = 700
    },
    {
      text_body = "Keep me"
    },
  ]
}`)
        })

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
                insightIdReplacements: new Map(),
            })

            expect(result.hcl).toContain(`tiles = [
    {
      insight_id = 600
    },
    {
      text_body = "Active"
    },
  ]`)
            expect(result.hcl).not.toContain('insight_id = 601')
        })
    })

    describe('falls back to hardcoded ids', () => {
        it('uses hardcoded insight_id when no replacement exists', () => {
            const dashboard = createTestDashboard({
                id: 13,
                name: 'Partial Refs',
                tiles: [
                    { id: 130, insight: { id: 1300 }, color: null, layouts: {} },
                    { id: 131, insight: { id: 1301 }, color: null, layouts: {} },
                ],
            })

            const result = generateDashboardLayoutHCL(dashboard, {
                dashboardTfReference: 'posthog_dashboard.partial_refs.id',
                insightIdReplacements: new Map([[1300, 'posthog_insight.replaced.id']]),
            })

            expect(result.hcl).toContain(`tiles = [
    {
      insight_id = posthog_insight.replaced.id
    },
    {
      insight_id = 1301
    },
  ]`)
        })
    })
})
