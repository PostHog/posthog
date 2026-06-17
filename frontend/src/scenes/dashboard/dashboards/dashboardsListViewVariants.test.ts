import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { DashboardsListViewVariant, resolveDashboardsListViewVariant } from './dashboardsListViewVariants'

describe('resolveDashboardsListViewVariant', () => {
    const cases: [string | boolean | undefined, DashboardsListViewVariant][] = [
        [undefined, 'control'],
        ['', 'control'],
        ['unknown', 'control'],
        [true, 'control'],
        ['control', 'control'],
        ['grid', 'grid'],
        ['finder', 'finder'],
    ]

    it.each(cases)('flag value %p resolves to %p', (value, expected) => {
        const featureFlags: FeatureFlagsSet = value === undefined ? {} : { [FEATURE_FLAGS.DASHBOARDS_LIST_VIEW]: value }
        expect(resolveDashboardsListViewVariant(featureFlags)).toBe(expected)
    })
})
