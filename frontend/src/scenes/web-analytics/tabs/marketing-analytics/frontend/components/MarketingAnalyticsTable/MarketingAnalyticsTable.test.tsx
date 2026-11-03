import { fireEvent, render, screen } from '@testing-library/react'

import { DataTableNode, MarketingAnalyticsDrillDownLevel, NodeKind } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { MarketingAnalyticsTable } from './MarketingAnalyticsTable'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: () => ({
        conversionRecordings: null,
        currentTeamId: 1,
        drillDownLevel: 'Campaign',
        nativeSourcesHierarchyStatus: null,
        conversion_goals: [],
        response: null,
        responseLoading: false,
    }),
    useActions: () => new Proxy({}, { get: () => jest.fn() }),
}))
jest.mock('@posthog/lemon-ui', () => ({
    LemonButton: ({ children }: { children?: React.ReactNode }) => <button>{children}</button>,
    LemonInput: ({ value, onChange }: { value: string; onChange: (value: string) => void }) => (
        <input aria-label="Search" value={value} onChange={(event) => onChange(event.target.value)} />
    ),
    LemonSelect: () => null,
    Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))
jest.mock('lib/hooks/useFeatureFlag', () => ({ useFeatureFlag: () => false }))
jest.mock('scenes/teamLogic', () => ({ teamLogic: {} }))
jest.mock('~/queries/nodes/DataNode/dataNodeLogic', () => ({ dataNodeLogic: () => ({}) }))
jest.mock('~/scenes/marketing-analytics/MarketingAnalyticsFreshness', () => ({
    MarketingAnalyticsFreshness: () => null,
}))
jest.mock('~/scenes/web-analytics/tiles/WebAnalyticsTile', () => ({ webAnalyticsDataTableQueryContext: {} }))
jest.mock('../../logic/marketingAnalyticsLogic', () => ({ marketingAnalyticsLogic: {} }))
jest.mock('../../logic/marketingAnalyticsSettingsLogic', () => ({ marketingAnalyticsSettingsLogic: {} }))
jest.mock('../../logic/marketingAnalyticsTableLogic', () => ({ marketingAnalyticsTableLogic: {} }))
jest.mock('../../shared', () => ({ MarketingAnalyticsCell: () => <span data-attr="cost-cell" /> }))
jest.mock('./MarketingAnalyticsColumnConfigModal', () => ({ MarketingAnalyticsColumnConfigModal: () => null }))
jest.mock('~/queries/Query/Query', () => ({
    Query: ({ query, context }: { query: DataTableNode; context: QueryContext }) => {
        const Cell = context.columns!['Cost'].render!
        return <Cell columnName="Cost" value={null} record={[]} query={query} recordIndex={0} rowCount={1} />
    },
}))

describe('MarketingAnalyticsTable', () => {
    it('keeps the mounted cells when the search term changes', () => {
        const query: DataTableNode = {
            kind: NodeKind.DataTableNode,
            source: {
                kind: NodeKind.MarketingAnalyticsTableQuery,
                select: ['Cost'],
                properties: [],
                drillDownLevel: MarketingAnalyticsDrillDownLevel.Campaign,
            },
        }
        render(<MarketingAnalyticsTable query={query} insightProps={{ dashboardItemId: 'new-marketing' }} />)
        const cellBefore = screen.getByTestId('cost-cell')

        fireEvent.change(screen.getByLabelText('Search'), { target: { value: 'spring' } })

        expect(screen.getByTestId('cost-cell')).toBe(cellBefore)
    })
})
