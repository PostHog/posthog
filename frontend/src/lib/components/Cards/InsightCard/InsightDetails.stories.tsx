import type { Meta, StoryObj } from '@storybook/react'

import { QueryBasedInsightModel } from '~/types'

import __dataTableEvents from '../../../../mocks/fixtures/api/projects/team_id/insights/dataTableEvents.json'
import __dataTableHogQL from '../../../../mocks/fixtures/api/projects/team_id/insights/dataTableHogQL.json'
import __dataVisualizationHogQL from '../../../../mocks/fixtures/api/projects/team_id/insights/dataVisualizationHogQL.json'
import __funnelLeftToRight from '../../../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json'
import __lifecycle from '../../../../mocks/fixtures/api/projects/team_id/insights/lifecycle.json'
import __retention from '../../../../mocks/fixtures/api/projects/team_id/insights/retention.json'
import __stickiness from '../../../../mocks/fixtures/api/projects/team_id/insights/stickiness.json'
import __trendsFormulas from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsFormulas.json'
import __trendsLine from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'
import __trendsLineMulti from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsLineMulti.json'
import __trendsPie from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsPie.json'
import __trendsTable from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsTable.json'
import __trendsValue from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsValue.json'
import __trendsWorldMap from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsWorldMap.json'
import __userPaths from '../../../../mocks/fixtures/api/projects/team_id/insights/userPaths.json'
import { InsightDetails as InsightDetailsComponent } from './InsightDetails'

type Story = StoryObj<{ insight: QueryBasedInsightModel }>
const meta: Meta<{ insight: QueryBasedInsightModel }> = {
    title: 'Components/Cards/Insight Details',
    component: InsightDetailsComponent as any,
    parameters: {
        mockDate: '2025-12-10',
    },
    render: ({ insight }) => {
        return (
            <div className="bg-surface-primary w-[24rem] p-4 rounded">
                <InsightDetailsComponent query={insight.query} footerInfo={insight} />
            </div>
        )
    },
}
export default meta

export const Trends: Story = {
    args: {
        insight: __trendsLine as any,
    },
}

export const TrendsMulti: Story = {
    args: {
        insight: __trendsLineMulti as any,
    },
}

export const TrendsHorizontalBar: Story = {
    args: {
        insight: __trendsValue as any,
    },
}

export const TrendsTable: Story = {
    args: { insight: __trendsTable as any },
}

export const TrendsPie: Story = {
    args: { insight: __trendsPie as any },
}

export const TrendsWorldMap: Story = {
    args: {
        insight: __trendsWorldMap as any,
    },
}

export const TrendsFormulas: Story = {
    args: {
        insight: __trendsFormulas as any,
    },
}

export const Funnel: Story = {
    args: {
        insight: __funnelLeftToRight as any,
    },
}

export const Retention: Story = {
    args: {
        insight: __retention as any,
    },
}

export const Paths: Story = {
    args: {
        insight: __userPaths as any,
    },
}

export const Stickiness: Story = {
    args: { insight: __stickiness as any },
}

export const Lifecycle: Story = {
    args: {
        insight: __lifecycle as any,
    },
}

export const DataTableHogQLQuery: Story = {
    args: {
        insight: __dataTableHogQL as any,
    },
}

export const DataVisualizationHogQLQuery: Story = {
    args: {
        insight: __dataVisualizationHogQL as any,
    },
}

export const DataTableEventsQuery: Story = {
    args: {
        insight: __dataTableEvents as any,
    },
}
