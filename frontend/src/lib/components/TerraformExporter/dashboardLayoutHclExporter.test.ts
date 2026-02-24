import { generateDashboardLayoutHCL } from 'lib/components/TerraformExporter/dashboardLayoutHclExporter'

import { DashboardType } from '~/types'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const createTestDashboard = (props: Record<string, any>): Partial<DashboardType> => props as Partial<DashboardType>

describe('dashboardLayoutHclExporter test', () => {
    describe('generates valid hcl', () => {
        it('generates insight tiles with TF references', () => {
            const dashboard = createTestDashboard({
                id: 1,
                name: 'My Dashboard',
                tiles: [{ id: 10, insight: { id: 100 }, color: null, layouts: {} }],
            })

            const result = generateDashboardLayoutHCL(dashboard, {
                dashboardTfReference: 'posthog_dashboard.my_dashboard.id',
                insightIdReplacements: new Map([[100, 'posthog_insight.my_insight.id']]),
            })

            expect(result.hcl).toContain('resource "posthog_dashboard_layout" "my_dashboard"')
            expect(result.hcl).toContain('dashboard_id = posthog_dashboard.my_dashboard.id')
            expect(result.hcl).toContain('insight_id = posthog_insight.my_insight.id')
            expect(result.warnings).toHaveLength(0)
        })

        it('generates text tiles', () => {
            const dashboard = createTestDashboard({
                id: 2,
                name: 'Text Dashboard',
                tiles: [{ id: 20, text: { body: 'Some markdown text' }, color: null, layouts: {} }],
            })

            const result = generateDashboardLayoutHCL(dashboard, {
                dashboardTfReference: 'posthog_dashboard.text_dashboard.id',
            })

            expect(result.hcl).toContain('text_body = "Some markdown text"')
            expect(result.hcl).not.toContain('insight_id')
        })

        it('includes tile color', () => {
            const dashboard = createTestDashboard({
                id: 3,
                name: 'Colored',
                tiles: [{ id: 30, text: { body: 'Note' }, color: 'blue', layouts: {} }],
            })

            const result = generateDashboardLayoutHCL(dashboard, {
                dashboardTfReference: 'posthog_dashboard.colored.id',
            })

            expect(result.hcl).toContain('color = "blue"')
        })

        it('serializes layouts as jsonencode', () => {
            const layouts = {
                sm: { x: 0, y: 0, w: 6, h: 5 },
                xs: { x: 0, y: 0, w: 1, h: 5 },
            }
            const dashboard = createTestDashboard({
                id: 4,
                name: 'With Layouts',
                tiles: [{ id: 40, insight: { id: 400 }, color: null, layouts }],
            })

            const result = generateDashboardLayoutHCL(dashboard, {
                dashboardTfReference: 'posthog_dashboard.with_layouts.id',
            })

            expect(result.hcl).toContain('layouts_json = jsonencode(')
            expect(result.hcl).toContain('"sm"')
            expect(result.hcl).toContain('"x": 0')
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

            expect(result.hcl).not.toContain('layouts_json')
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

            expect(result.hcl).toContain('insight_id = 600')
            expect(result.hcl).not.toContain('insight_id = 601')
            expect(result.hcl).toContain('text_body = "Active"')
        })
    })

    describe('import block', () => {
        it('generates import block for saved dashboards', () => {
            const dashboard = createTestDashboard({
                id: 7,
                name: 'Saved',
                tiles: [{ id: 70, insight: { id: 700 }, color: null, layouts: {} }],
            })

            const result = generateDashboardLayoutHCL(dashboard, {
                dashboardTfReference: 'posthog_dashboard.saved.id',
                projectId: 42,
            })

            expect(result.hcl).toContain('import {')
            expect(result.hcl).toContain('to = posthog_dashboard_layout.saved')
            expect(result.hcl).toContain('id = "42/7"')
        })

        it('excludes import block when includeImport is false', () => {
            const dashboard = createTestDashboard({
                id: 8,
                name: 'No Import',
                tiles: [{ id: 80, insight: { id: 800 }, color: null, layouts: {} }],
            })

            const result = generateDashboardLayoutHCL(dashboard, {
                dashboardTfReference: 'posthog_dashboard.no_import.id',
                includeImport: false,
            })

            expect(result.hcl).not.toContain('import {')
        })

        it('excludes import block for new dashboards', () => {
            const dashboard = createTestDashboard({
                name: 'New',
                tiles: [{ id: 90, text: { body: 'Note' }, color: null, layouts: {} }],
            })

            const result = generateDashboardLayoutHCL(dashboard)

            expect(result.hcl).not.toContain('import {')
        })
    })

    describe('warnings', () => {
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

            expect(result.hcl).toContain('insight_id = 1200')
        })
    })
})
