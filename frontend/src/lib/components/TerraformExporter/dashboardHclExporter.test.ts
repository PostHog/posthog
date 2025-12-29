import { generateDashboardHCL } from 'lib/components/TerraformExporter/dashboardHclExporter'

import { DashboardBasicType } from '~/types'

const createTestDashboard = (props: Record<string, unknown>): Partial<DashboardBasicType> =>
    props as Partial<DashboardBasicType>

describe('dashboardHclExporter test', () => {
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
            const dashboard = createTestDashboard({ name: input })

            const hcl = generateDashboardHCL(dashboard).hcl

            expect(hcl).toContain(`resource "posthog_dashboard" "${expected}"`)
        })
    })

    describe('generates valid hcl', () => {
        it('generates valid HCL for a complete dashboard', () => {
            const dashboard = createTestDashboard({
                id: 123,
                name: 'My Test Dashboard',
                description: 'A test dashboard for unit testing',
                pinned: true,
                tags: ['test', 'analytics'],
            })

            const result = generateDashboardHCL(dashboard)
            const hcl = result.hcl

            expect(hcl).toContain('resource "posthog_dashboard" "my_test_dashboard"')
            expect(hcl).toContain('name = "My Test Dashboard"')
            expect(hcl).toContain('description = "A test dashboard for unit testing"')
            expect(hcl).toContain('pinned = true')
            expect(hcl).toContain('tags = ["test", "analytics", "managed-by:terraform"]')

            expect(result.warnings).toHaveLength(0)
        })

        it('includes import block for saved dashboards by default', () => {
            const dashboard = createTestDashboard({
                id: 456,
                name: 'Saved Dashboard',
            })

            const result = generateDashboardHCL(dashboard)
            const hcl = result.hcl

            expect(hcl).toContain('import {')
            expect(hcl).toContain('to = posthog_dashboard.saved_dashboard')
            expect(hcl).toContain('id = "456"')

            expect(result.warnings).toHaveLength(0)
        })

        it('excludes import block for new dashboards', () => {
            const dashboard = createTestDashboard({
                name: 'New Dashboard',
            })

            const result = generateDashboardHCL(dashboard)
            const hcl = result.hcl

            expect(hcl).not.toContain('import {')

            expect(result.warnings).toHaveLength(0)
        })

        it('respects includeImport option', () => {
            const dashboard = createTestDashboard({
                id: 789,
                name: 'Test Dashboard',
            })

            const hclWithImport = generateDashboardHCL(dashboard, { includeImport: true }).hcl
            const hclWithoutImport = generateDashboardHCL(dashboard, { includeImport: false }).hcl

            expect(hclWithImport).toContain('import {')
            expect(hclWithoutImport).not.toContain('import {')
        })

        it('also includes pinned when false', () => {
            const dashboard = createTestDashboard({
                name: 'Test',
                pinned: false,
            })

            const hcl = generateDashboardHCL(dashboard).hcl

            expect(hcl).toContain('pinned')
        })

        it('includes provider version comment', () => {
            const dashboard = createTestDashboard({
                name: 'Test',
            })

            const hcl = generateDashboardHCL(dashboard).hcl

            expect(hcl).toMatch(/# Compatible with posthog provider v\d+\.\d+/)
        })
    })

    describe('generates expected warnings', () => {
        it('warns when name is missing', () => {
            const dashboard = createTestDashboard({
                id: 123,
            })

            const result = generateDashboardHCL(dashboard)

            expect(result.warnings).toHaveLength(1)
            expect(result.warnings).toContain(
                'No name provided. Consider adding a name for better identification in Terraform state.'
            )
        })
    })

    describe('correctly handles the managed-by:terraform tag', () => {
        it('adds managed-by:terraform tag when no tags exist', () => {
            const dashboard = createTestDashboard({
                name: 'No Tags',
            })

            const hcl = generateDashboardHCL(dashboard).hcl

            expect(hcl).toContain('tags = ["managed-by:terraform"]')
        })

        it('appends managed-by:terraform tag to existing tags', () => {
            const dashboard = createTestDashboard({
                name: 'Has Tags',
                tags: ['existing', 'tags'],
            })

            const hcl = generateDashboardHCL(dashboard).hcl

            expect(hcl).toContain('tags = ["existing", "tags", "managed-by:terraform"]')
        })

        it('does not duplicate managed-by:terraform tag if already present', () => {
            const dashboard = createTestDashboard({
                name: 'Already Tagged',
                tags: ['other', 'managed-by:terraform'],
            })

            const hcl = generateDashboardHCL(dashboard).hcl

            expect(hcl).toContain('tags = ["other", "managed-by:terraform"]')
            expect(hcl).not.toContain('tags = ["other", "managed-by:terraform", "managed-by:terraform"]')
        })
    })
})
