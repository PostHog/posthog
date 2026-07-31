import type { Meta, StoryObj } from '@storybook/react'
import { BindLogic } from 'kea'
import { useState } from 'react'

import {
    funnelResultTrends,
    funnelResultTrendsCompare,
    funnelResultTrendsCompareWithBreakdown,
} from 'scenes/funnels/__mocks__/funnelDataLogicMocks'
import { insightLogic } from 'scenes/insights/insightLogic'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/InsightViz'
import { getCachedResults } from '~/queries/nodes/InsightViz/utils'
import { InsightLogicProps } from '~/types'

import __funnelHistoricalTrends from '../../../../mocks/fixtures/api/projects/team_id/insights/funnelHistoricalTrends.json'
import { FunnelTrendsTable } from './FunnelTrendsTable'

let uniqueNode = 0

// Render the trends detailed-results table from a cached funnel-trends result, swapping the
// historical-trends fixture's `result` payload so each story can show a different series shape.
function TrendsTableStory({ result }: { result: Record<string, any>[] }): JSX.Element {
    const [dashboardItemId] = useState(() => `FunnelTrendsTableStory.${uniqueNode++}`)

    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const baseInsight = __funnelHistoricalTrends as any
    const insight = { ...baseInsight, result }
    const cachedInsight = { ...insight, short_id: dashboardItemId }
    const insightProps = { dashboardItemId, doNotLoad: true, cachedInsight } as InsightLogicProps
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: insight.query.source,
        key: insightVizDataNodeKey(insightProps),
        cachedResults: getCachedResults(insightProps.cachedInsight, insight.query.source),
        doNotLoad: insightProps.doNotLoad,
    }

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <FunnelTrendsTable />
            </BindLogic>
        </BindLogic>
    )
}

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Insights/FunnelTrendsTable',
    component: FunnelTrendsTable,
    parameters: { mockDate: '2023-03-01' },
}
export default meta

export const Default: Story = {
    render: () => <TrendsTableStory result={funnelResultTrends.result} />,
}

export const Compare: Story = {
    render: () => <TrendsTableStory result={funnelResultTrendsCompare.result} />,
}

export const CompareWithBreakdown: Story = {
    render: () => <TrendsTableStory result={funnelResultTrendsCompareWithBreakdown.result} />,
}
