import { cleanup, render, screen } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { AnalyticsProductHome } from './AnalyticsProductHome'

jest.mock('products/product_analytics/frontend/insights/home/HomeTab', () => ({
    HomeTab: () => <div>Product analytics dashboard</div>,
}))

jest.mock('./AnalyticsCreateModals', () => ({
    AnalyticsCreateModals: () => null,
}))

jest.mock('~/layout/scenes/components/SceneTitleSection', () => ({
    SceneTitleSection: () => null,
}))

describe('AnalyticsProductHome', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(cleanup)

    test.each([
        [true, undefined],
        [true, false],
        [true, 'control'],
        [true, 'test'],
        [true, true],
        [false, undefined],
        [false, false],
        [false, 'control'],
        [false, 'test'],
        [false, true],
    ] as const)('shows the dashboard with rail %s and Home flag %s', (railEnabled, homeFlag) => {
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.TODAY_RAIL_NAV]: railEnabled,
            ...(homeFlag === undefined ? {} : { [FEATURE_FLAGS.PRODUCT_ANALYTICS_HOME_TAB]: homeFlag }),
        })

        render(<AnalyticsProductHome />)

        expect(screen.queryByText('Product analytics dashboard') !== null).toBe(railEnabled)
    })
})
