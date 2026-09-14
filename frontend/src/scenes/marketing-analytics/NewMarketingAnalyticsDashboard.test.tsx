import { cleanup, render, screen } from '@testing-library/react'
import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'

import { NewMarketingAnalyticsDashboard } from './NewMarketingAnalyticsDashboard'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useValues: jest.fn(), useActions: () => ({}) }))
jest.mock('@posthog/lemon-ui', () => ({ LemonBanner: () => null, LemonButton: () => null, LemonSkeleton: () => null }))
jest.mock('lib/components/CompareFilter/CompareFilter', () => ({ CompareFilter: () => null }))
jest.mock('lib/components/DateFilter/DateFilter', () => ({ DateFilter: () => null }))
jest.mock('lib/logic/featureFlagLogic', () => ({ featureFlagLogic: {} }))
jest.mock('scenes/web-analytics/common', () => ({ MARKETING_ANALYTICS_DEFAULT_QUERY_TAGS: {} }))
jest.mock('scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic', () => ({
    marketingAnalyticsLogic: {},
}))
jest.mock('scenes/web-analytics/tabs/marketing-analytics/frontend/shared', () => ({
    MarketingAnalyticsCell: () => null,
}))
jest.mock('scenes/web-analytics/tiles/WebAnalyticsTile', () => ({ webAnalyticsDataTableQueryContext: {} }))
jest.mock('~/queries/nodes/DataNode/dataNodeLogic', () => ({ dataNodeLogic: () => ({}) }))
jest.mock('~/queries/nodes/OverviewGrid/OverviewMetricCardGrid', () => ({ OverviewMetricCardGrid: () => null }))
jest.mock('~/queries/nodes/WebOverview/WebOverview', () => ({ labelFromKey: () => '' }))
jest.mock('~/queries/Query/Query', () => ({ Query: () => null }))
jest.mock('scenes/web-analytics/tabs/marketing-analytics/frontend/components/AttributionTab/AttributionTab', () => ({
    AttributionTab: () => <div>Attribution explorer</div>,
}))
jest.mock('scenes/teamLogic', () => ({ teamLogic: {} }))
jest.mock('scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAttributionLogic', () => ({
    marketingAttributionLogic: {},
}))
jest.mock('scenes/web-analytics/tabs/marketing-analytics/frontend/components/AttributionTab/AttributionTable', () => ({
    AttributionTable: () => null,
}))
jest.mock('scenes/web-analytics/tabs/marketing-analytics/frontend/components/RetentionTab/RetentionTab', () => ({
    RetentionTab: () => <div>Retention explorer</div>,
}))

describe('NewMarketingAnalyticsDashboard', () => {
    afterEach(cleanup)

    it.each([
        [false, false],
        [true, false],
        [false, true],
        [true, true],
    ])('keeps conversion (%s) and retention (%s) independently gated alongside traffic', (conversion, retention) => {
        jest.mocked(useValues).mockReturnValue({
            featureFlags: {
                [FEATURE_FLAGS.MARKETING_ANALYTICS_ATTRIBUTION]: conversion,
                [FEATURE_FLAGS.MARKETING_ANALYTICS_RETENTION]: retention,
            },
            dateFilter: { dateFrom: '-30d', dateTo: null },
            compareFilter: { compare: false },
            shouldFilterTestAccounts: false,
            responseLoading: false,
        })

        render(<NewMarketingAnalyticsDashboard />)

        expect(screen.getByText('Acquisition')).not.toBeNull()
        expect(screen.getByText('Engagement')).not.toBeNull()
        expect(screen.queryByText('Attribution explorer') !== null).toBe(conversion)
        expect(screen.queryByText('Retention explorer') !== null).toBe(retention)
    })
})
