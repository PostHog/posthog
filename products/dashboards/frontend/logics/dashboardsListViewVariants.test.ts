import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { DashboardsListViewVariant, resolveDashboardsListViewVariant } from './dashboardsListViewVariants'

// Experiment cleanup: flag `dashboards-list-view` · experiment 379125 — remove with the tree arm.
describe('resolveDashboardsListViewVariant', () => {
    const cases: [string | boolean | undefined, DashboardsListViewVariant][] = [
        [undefined, 'control'],
        ['', 'control'],
        ['unknown', 'control'],
        [true, 'control'],
        ['control', 'control'],
        ['tree', 'tree'],
        // Retired arm names now fall back to control rather than enrolling a treatment arm.
        ['explorer', 'control'],
        ['grid', 'control'],
        ['finder', 'control'],
    ]

    it.each(cases)('flag value %p resolves to %p', (value, expected) => {
        const featureFlags: FeatureFlagsSet = value === undefined ? {} : { [FEATURE_FLAGS.DASHBOARDS_LIST_VIEW]: value }
        expect(resolveDashboardsListViewVariant(featureFlags)).toBe(expected)
    })
})
