import { dashboardFiltersChangeWidgets } from './DashboardWidgetFiltersNotice'
import type { DashboardWidgetRunResultApi } from './generated/api.schemas'

function runResult(overrides: Partial<DashboardWidgetRunResultApi>): DashboardWidgetRunResultApi {
    return { tile_id: 1, widget_type: 'error_tracking_list', result: {}, error: null, ...overrides }
}

describe('dashboardFiltersChangeWidgets', () => {
    it.each([
        ['a widget that a dashboard filter changed', [runResult({ dashboard_filters_applied: true })], true],
        // No dashboard filter set, or the widget type takes none of them.
        ['widgets that no dashboard filter changed', [runResult({ dashboard_filters_applied: false })], false],
        ['a response from before the field existed', [runResult({})], false],
        // A failed tile shows an error, not results that could look different.
        ['a failed widget', [runResult({ dashboard_filters_applied: true, error: 'Widget query failed.' })], false],
        ['no widgets', [], false],
    ])('%s', (_name, results, expected) => {
        const resultsByTileId = Object.fromEntries(results.map((result, index) => [index, result]))

        expect(dashboardFiltersChangeWidgets(resultsByTileId)).toBe(expected)
    })
})
