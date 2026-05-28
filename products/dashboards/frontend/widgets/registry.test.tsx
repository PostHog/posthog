import posthog from 'posthog-js'

import { DASHBOARD_WIDGET_CATALOG } from '../widget_types/catalog'
import { EXPECTED_DASHBOARD_WIDGET_TYPES } from '../widget_types/expectedWidgetTypes'

import { getDashboardWidgetDefinition } from './registry'
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
        expect(definition?.Component).toBeDefined()
        expect(definition?.EditModal).toBeDefined()
        expect(definition?.productAccess).toBe('error_tracking')
        expect(posthog.captureException).not.toHaveBeenCalled()
    })

    it('registers session_replay_list widget', () => {
        const definition = getDashboardWidgetDefinition('session_replay_list')
        expect(definition?.Component).toBeDefined()
        expect(definition?.EditModal).toBeDefined()
        expect(definition?.productAccess).toBe('session_recording')
    })

    it('resolves error_tracking widget type alias', () => {
        expect(getDashboardWidgetDefinition('error_tracking')).toBe(getDashboardWidgetDefinition('error_tracking_list'))
        expect(posthog.captureException).not.toHaveBeenCalled()
    })

    it('registers every catalog key', () => {
        for (const key of Object.keys(DASHBOARD_WIDGET_CATALOG)) {
            expect(getDashboardWidgetDefinition(key)).toBeDefined()
        }
    })

    it('catalog keys match backend expected widget types', () => {
        expect(Object.keys(DASHBOARD_WIDGET_CATALOG).sort()).toEqual([...EXPECTED_DASHBOARD_WIDGET_TYPES].sort())
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
