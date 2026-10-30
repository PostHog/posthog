import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { cleanup, render, screen } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { AnalyticsProductHome } from './AnalyticsProductHome'

jest.mock('products/product_analytics/frontend/insights/home/HomeTab', () => ({
    HomeTab: ({ page }: { page: { title: JSX.Element } }) => (
        <>
            {page.title}
            <div>Product analytics dashboard</div>
        </>
    ),
}))

jest.mock('products/product_analytics/frontend/insights/home/HomeDashboardModals', () => ({
    HomeDashboardModals: () => null,
}))

jest.mock('./AnalyticsCreateModals', () => ({
    AnalyticsCreateModals: () => null,
}))

jest.mock('~/layout/scenes/components/SceneTitleSection', () => ({
    SceneTitleSection: ({ actions }: { actions?: JSX.Element }) => <div>{actions}</div>,
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

    test.each([
        ['the default dashboard', null, 'home-tab-choose-dashboard'],
        ['a custom dashboard', 42, 'home-tab-dashboard-options'],
    ])('shows a labeled Customize control for %s', (_scenario, homeDashboardId, expectedDataAttr) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TODAY_RAIL_NAV]: true })
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, home_tab_dashboard: homeDashboardId })

        const { container } = render(<AnalyticsProductHome />)

        expect(container.querySelector(`[data-attr="${expectedDataAttr}"]`)?.textContent).toBe('Customize')
    })
})
