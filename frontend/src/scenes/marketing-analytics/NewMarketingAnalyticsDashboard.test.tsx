import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'

import { NewMarketingAnalyticsDashboard } from './NewMarketingAnalyticsDashboard'

jest.mock('./Setup/sectionRouting', () => ({ suggestionsForSection: () => [] }))

jest.mock('./Setup/SuggestionRow', () => ({ SuggestionRow: () => null }))

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useValues: jest.fn(), useActions: () => ({}) }))
jest.mock('@posthog/lemon-ui', () => ({
    LemonBanner: () => null,
    LemonSelect: ({
        value,
        onChange,
        options,
    }: {
        value: string
        onChange: (value: string) => void
        options: { value: string; label: string }[]
    }) => (
        <select aria-label="Traffic breakdown" value={value} onChange={(event) => onChange(event.target.value)}>
            {options.map((option) => (
                <option key={option.value} value={option.value}>
                    {option.label}
                </option>
            ))}
        </select>
    ),
    LemonButton: ({
        children,
        onClick,
        'aria-pressed': pressed,
    }: {
        children: React.ReactNode
        onClick: () => void
        'aria-pressed'?: boolean
    }) => (
        <button onClick={onClick} aria-pressed={pressed}>
            {children}
        </button>
    ),
    LemonSkeleton: () => null,
}))
jest.mock('lib/components/CompareFilter/CompareFilter', () => ({ CompareFilter: () => <div>Compare periods</div> }))
jest.mock('lib/components/DateFilter/DateFilter', () => ({ DateFilter: () => null }))
jest.mock('lib/logic/featureFlagLogic', () => ({ featureFlagLogic: {} }))
jest.mock('scenes/web-analytics/common', () => ({ MARKETING_ANALYTICS_DEFAULT_QUERY_TAGS: {} }))
jest.mock('scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic', () => ({
    marketingAnalyticsLogic: {},
    SetupSection: { CONVERSION_GOALS: 'conversion-goals' },
}))
jest.mock('scenes/web-analytics/tabs/marketing-analytics/frontend/shared', () => ({
    MarketingAnalyticsCell: () => null,
}))
jest.mock('scenes/web-analytics/tiles/WebAnalyticsTile', () => ({ webAnalyticsDataTableQueryContext: {} }))
jest.mock('~/queries/nodes/DataNode/dataNodeLogic', () => ({ dataNodeLogic: () => ({}) }))
jest.mock('~/queries/nodes/OverviewGrid/OverviewMetricCardGrid', () => ({ OverviewMetricCardGrid: () => null }))
jest.mock('~/queries/nodes/WebOverview/WebOverview', () => ({ labelFromKey: () => '' }))
jest.mock('~/queries/Query/Query', () => ({
    Query: ({ query }: { query: unknown }) => <div data-attr="traffic-query">{JSON.stringify(query)}</div>,
}))
jest.mock('scenes/web-analytics/tabs/marketing-analytics/frontend/components/AttributionTab/AttributionTab', () => ({
    AttributionTab: () => <div>Attribution explorer</div>,
}))
jest.mock('scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic', () => ({ setupPlanLogic: {} }))

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
            setupPlan: {},
            visibleSuggestions: [],
        })

        render(<NewMarketingAnalyticsDashboard />)

        expect(screen.getByLabelText('Acquisition')).not.toBeNull()
        expect(screen.queryByText('Compare periods')).not.toBeNull()
        expect(screen.queryByText('Reload summary')).not.toBeNull()
        expect(screen.getByText('Engagement')).not.toBeNull()
        expect(screen.queryByText('Attribution explorer')).toBeNull()
        expect(screen.queryByText('Retention explorer')).toBeNull()
        fireEvent.change(screen.getByLabelText('Traffic breakdown'), { target: { value: 'InitialUTMCampaign' } })
        expect(JSON.parse(screen.getByTestId('traffic-query').textContent || '{}').source).toMatchObject({
            kind: 'WebStatsTableQuery',
            breakdownBy: 'InitialUTMCampaign',
            includeBounceRate: false,
            dateRange: { date_from: '-30d', date_to: null },
            compareFilter: { compare: false },
        })
        fireEvent.click(screen.getByText('Engagement'))
        expect(JSON.parse(screen.getByTestId('traffic-query').textContent || '{}')).toMatchObject({
            hiddenColumns: ['context.columns.views'],
            source: {
                breakdownBy: 'InitialUTMCampaign',
                includeBounceRate: true,
                dateRange: { date_from: '-30d', date_to: null },
                compareFilter: { compare: false },
            },
        })
        expect(screen.queryByLabelText('Acquisition')).toBeNull()
        expect(screen.getByLabelText('Engagement')).not.toBeNull()
        expect(screen.queryByText('Conversion') !== null).toBe(conversion)
        expect(screen.queryByText('Retention') !== null).toBe(retention)
        expect(screen.queryByText('Revenue') !== null).toBe(conversion)
        if (conversion) {
            fireEvent.click(screen.getByText('Conversion'))
        }
        expect(screen.queryByText('Attribution explorer') !== null).toBe(conversion)
        expect(screen.queryByLabelText('Engagement') !== null).toBe(!conversion)
        if (conversion) {
            fireEvent.click(screen.getByText('Revenue'))
        }
        expect(screen.queryByText('Attribution explorer')).toBeNull()
        expect(screen.queryByLabelText('Revenue') !== null).toBe(conversion)
        if (retention) {
            fireEvent.click(screen.getByText('Retention'))
        }
        expect(screen.queryByText('Retention explorer') !== null).toBe(retention)
        expect(screen.queryByText('Compare periods') !== null).toBe(!conversion && !retention)
        expect(screen.queryByText('Reload summary') !== null).toBe(!conversion && !retention)
        expect(screen.queryByText('Attribution explorer')).toBeNull()
        fireEvent.click(screen.getByText('Acquisition'))
        expect(screen.getByLabelText('Acquisition')).not.toBeNull()
        expect(screen.queryByText('Compare periods')).not.toBeNull()
        expect(screen.queryByText('Reload summary')).not.toBeNull()
        expect(screen.queryByText('Retention explorer')).toBeNull()
    })
})
