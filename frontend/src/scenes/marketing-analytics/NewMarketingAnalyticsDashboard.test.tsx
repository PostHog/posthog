import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useValues } from 'kea'

import { NewMarketingAnalyticsDashboard } from 'products/marketing_analytics/frontend/dashboard/NewMarketingAnalyticsDashboard'

jest.mock('scenes/marketing-analytics/Setup/sectionRouting', () => ({ suggestionsForSection: () => [] }))

jest.mock('scenes/marketing-analytics/Setup/SuggestionRow', () => ({ SuggestionRow: () => null }))

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: () => new Proxy({}, { get: () => jest.fn() }),
}))
jest.mock('@posthog/lemon-ui', () => ({
    LemonBanner: ({ children }: { children: React.ReactNode }) => <div role="alert">{children}</div>,
    LemonCard: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    LemonSelect: ({
        value,
        onChange,
        options,
        'aria-label': label,
    }: {
        value: string
        onChange: (value: string) => void
        options: { value: string; label: string }[]
        'aria-label': string
    }) => (
        <select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>
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
jest.mock('scenes/web-analytics/tiles/WebAnalyticsTile', () => ({
    VariationCell: () => () => null,
    webAnalyticsDataTableQueryContext: {},
}))
jest.mock('~/queries/nodes/DataNode/dataNodeLogic', () => ({ dataNodeLogic: (props: { key: string }) => ({ props }) }))
jest.mock('~/queries/nodes/OverviewGrid/OverviewMetricCardGrid', () => ({ OverviewMetricCardGrid: () => null }))
jest.mock('~/queries/nodes/WebOverview/WebOverview', () => ({ labelFromKey: () => '' }))
jest.mock('~/queries/Query/Query', () => ({
    Query: ({ query }: { query: { kind: string } }) => (
        <div data-attr={query.kind === 'DataTableNode' ? 'traffic-query' : 'trend-query'}>{JSON.stringify(query)}</div>
    ),
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
        ['marketing-acquisition-overview', 'failed-traffic-query', 'current-traffic-query', 'failed-traffic-query'],
        ['marketing-acquisition-overview', undefined, 'current-traffic-query', 'current-traffic-query'],
        ['marketing-acquisition-customers', 'failed-customer-query', 'current-customer-query', 'failed-customer-query'],
        ['marketing-acquisition-customers', undefined, 'current-customer-query', 'current-customer-query'],
        ['marketing-acquisition-overview', undefined, null, null],
    ])('identifies the failed %s request with error ID %s and request ID %s', (key, errorId, requestId, expected) => {
        jest.mocked(useValues).mockImplementation((logic) => ({
            dateFilter: { dateFrom: '-30d', dateTo: null },
            compareFilter: { compare: false },
            shouldFilterTestAccounts: false,
            responseLoading: false,
            setupPlan: {},
            visibleSuggestions: [],
            trafficOrderBy: {},
            trafficChartMetric: 'visitors',
            trafficChartSeries: { kind: 'EventsNode', event: null, math: 'dau', custom_name: 'Visitors' },
            customerConversionGoal: { kind: 'EventsNode', event: 'purchase' },
            customerGoals: [],
            ...(typeof logic !== 'function' && (logic as { props?: { key?: string } }).props?.key === key
                ? {
                      responseError: 'Query failed',
                      responseErrorObject: { queryId: errorId },
                      queryId: requestId,
                      response: { query_status: { id: 'previous-successful-query' } },
                  }
                : {}),
        }))

        render(<NewMarketingAnalyticsDashboard />)

        const error = screen.getByRole('alert')
        expect(error.textContent?.match(/Query ID: (.+)/)?.[1] ?? null).toBe(expected)
        expect(error.textContent).not.toContain('previous-successful-query')
    })

    it('shows every section without per-section flags', () => {
        jest.mocked(useValues).mockReturnValue({
            dateFilter: { dateFrom: '-30d', dateTo: null },
            compareFilter: { compare: false },
            shouldFilterTestAccounts: false,
            responseLoading: false,
            setupPlan: {},
            visibleSuggestions: [],
            trafficOrderBy: {},
            trafficChartMetric: 'visitors',
            trafficChartSeries: { kind: 'EventsNode', event: null, math: 'dau', custom_name: 'Visitors' },
        })

        render(<NewMarketingAnalyticsDashboard />)

        expect(screen.getByLabelText('Acquisition')).not.toBeNull()
        expect(screen.queryByText('Compare periods')).not.toBeNull()
        expect(screen.queryByText('Reload summary')).not.toBeNull()
        expect(screen.getByText('Engagement')).not.toBeNull()
        expect(screen.queryByText('Attribution explorer')).toBeNull()
        expect(screen.queryByText('Retention explorer')).toBeNull()
        expect(screen.getByText('Visitors over time')).not.toBeNull()
        expect(screen.getByLabelText('Chart metric')).not.toBeNull()
        const trendBeforeBreakdown = screen.getByTestId('trend-query').textContent
        expect(JSON.parse(trendBeforeBreakdown || '{}').source.series).toEqual([
            { kind: 'EventsNode', event: null, math: 'dau', custom_name: 'Visitors' },
        ])
        fireEvent.change(screen.getByLabelText('Traffic breakdown'), { target: { value: 'InitialUTMCampaign' } })
        expect(JSON.parse(screen.getByTestId('traffic-query').textContent || '{}').source).toMatchObject({
            kind: 'WebStatsTableQuery',
            breakdownBy: 'InitialUTMCampaign',
            includeBounceRate: false,
            dateRange: { date_from: '-30d', date_to: null },
            compareFilter: { compare: false },
        })
        expect(screen.getByTestId('trend-query').textContent).toBe(trendBeforeBreakdown)
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
        fireEvent.click(screen.getByText('Conversion'))
        expect(screen.getByText('Attribution explorer')).not.toBeNull()
        expect(screen.queryByLabelText('Engagement')).toBeNull()
        fireEvent.click(screen.getByText('Revenue'))
        expect(screen.queryByText('Attribution explorer')).toBeNull()
        expect(screen.getByLabelText('Revenue')).not.toBeNull()
        fireEvent.click(screen.getByText('Retention'))
        expect(screen.getByText('Retention explorer')).not.toBeNull()
        expect(screen.queryByText('Compare periods')).toBeNull()
        expect(screen.queryByText('Reload summary')).toBeNull()
        fireEvent.click(screen.getByText('Acquisition'))
        expect(screen.getByLabelText('Acquisition')).not.toBeNull()
        expect(screen.queryByText('Compare periods')).not.toBeNull()
        expect(screen.queryByText('Reload summary')).not.toBeNull()
        expect(screen.queryByText('Retention explorer')).toBeNull()
    })
})
