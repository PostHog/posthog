import posthog from 'posthog-js'

import { DASHBOARD_WIDGET_CATALOG } from '../widget_types/catalog'
import { getDashboardWidgetDefinition, parseDashboardWidgetConfigApiError } from './registry'
import { resetDashboardWidgetRegistryReportingForTests } from './registry'

jest.mock('posthog-js', () => ({
    __esModule: true,
    default: {
        captureException: jest.fn(),
    },
}))

describe('dashboard widget registry', () => {
    beforeEach(() => {
        jest.mocked(posthog.captureException).mockClear()
        resetDashboardWidgetRegistryReportingForTests()
    })

    it('registers error_tracking_list widget', () => {
        const definition = getDashboardWidgetDefinition('error_tracking_list')
        expect(definition?.Component).toBeTruthy()
        expect(definition?.EditModal).toBeTruthy()
        expect(definition?.productAccess).toBe('error_tracking')
        expect(definition?.parseConfigApiError).toBeTruthy()
        expect(posthog.captureException).not.toHaveBeenCalled()
    })

    it('delegates config api error parsing to the widget registry entry', () => {
        expect(parseDashboardWidgetConfigApiError('unknown_widget_type', new Error('nope'), {})).toBeNull()
        expect(parseDashboardWidgetConfigApiError('error_tracking_list', new Error('nope'), {})).toBeNull()
    })

    it('registers every catalog key', () => {
        for (const key of Object.keys(DASHBOARD_WIDGET_CATALOG)) {
            expect(getDashboardWidgetDefinition(key)).not.toBeUndefined()
        }
    })

    it('reports unknown widget types to PostHog once per canonical type', () => {
        expect(getDashboardWidgetDefinition('unknown_widget_type')).toBeUndefined()
        expect(getDashboardWidgetDefinition('unknown_widget_type')).toBeUndefined()

        expect(posthog.captureException).toHaveBeenCalledTimes(1)
        expect(posthog.captureException).toHaveBeenCalledWith(
            expect.objectContaining({
                message: 'Dashboard widget type has no frontend registry implementation',
            }),
            expect.objectContaining({
                feature: 'dashboard_widget',
                widget_type: 'unknown_widget_type',
                canonical_widget_type: 'unknown_widget_type',
                has_catalog_entry: false,
            })
        )
    })

    it('includes tile context when provided', () => {
        getDashboardWidgetDefinition('unknown_widget_type', { tileId: 42, dashboardId: 7 })

        expect(posthog.captureException).toHaveBeenCalledWith(
            expect.any(Error),
            expect.objectContaining({
                tile_id: 42,
                dashboard_id: 7,
            })
        )
    })
})
