import { render } from '@testing-library/react'

import { AdvancedActivityLogFilters, ExportedAsset } from './advancedActivityLogsLogic'
import { getFilterSummary, getFilterTooltip } from './ExportsListHelpers'

describe('ExportsListHelpers', () => {
    const exportAsset = (filters: AdvancedActivityLogFilters): ExportedAsset => ({
        id: 'export-1',
        export_format: 'text/csv',
        created_at: '2026-01-01T00:00:00Z',
        has_content: true,
        filename: 'activity.csv',
        expires_after: '2026-02-01T00:00:00Z',
        exception: null,
        export_context: { filters },
    })

    const tooltipText = (filters: AdvancedActivityLogFilters): string =>
        render(getFilterTooltip(exportAsset(filters))).container.textContent ?? ''

    test.each([
        ['exclude_users', ['auditor@example.com'], 'Excluded users: 1'],
        ['exclude_clients', ['local-build'], 'Excluded clients: 1'],
        ['exclude_ip_addresses', ['203.0.113.*', '198.51.100.7'], 'Excluded IP addresses: 2'],
    ] as const)('counts %s in the summary', (field, values, expected) => {
        const summary = getFilterSummary(exportAsset({ [field]: values } as AdvancedActivityLogFilters))

        expect(summary).toEqual(expected)
    })

    test.each([
        ['exact', 'equals'],
        ['contains', 'contains'],
        ['in', 'is one of'],
        ['not_in', 'is none of'],
    ] as const)('describes a %s detail filter as "%s"', (operation, label) => {
        const text = tooltipText({ detail_filters: { 'changes[].field': { operation, value: ['name'] } } })

        expect(text).toContain(`changes[].field ${label} "name"`)
    })

    it('lists the excluded values in the tooltip', () => {
        const text = tooltipText({
            exclude_users: ['auditor@example.com'],
            exclude_clients: ['local-build'],
            exclude_ip_addresses: ['203.0.113.*'],
        })

        expect(text).toContain('Excluded users (1):auditor@example.com')
        expect(text).toContain('Excluded clients (1):local-build')
        expect(text).toContain('Excluded IP addresses (1):203.0.113.*')
    })
})
