import type { Meta, StoryObj } from '@storybook/react'

import { QueryBasedInsightModel } from '~/types'

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
        insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'),
    },
}

export const TrendsMulti: Story = {
    args: {
        insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsLineMulti.json'),
    },
}

export const TrendsHorizontalBar: Story = {
    args: {
        insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsValue.json'),
    },
}

export const TrendsTable: Story = {
    args: { insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsTable.json') },
}

export const TrendsPie: Story = {
    args: { insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsPie.json') },
}

export const TrendsWorldMap: Story = {
    args: {
        insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsWorldMap.json'),
    },
}

export const TrendsFormulas: Story = {
    args: {
        insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsFormulas.json'),
    },
}

export const Funnel: Story = {
    args: {
        insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json'),
    },
}

export const Retention: Story = {
    args: {
        insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/retention.json'),
    },
}

export const Paths: Story = {
    args: {
        insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/userPaths.json'),
    },
}

export const Stickiness: Story = {
    args: { insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/stickiness.json') },
}

export const Lifecycle: Story = {
    args: {
        insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/lifecycle.json'),
    },
}

export const DataTableHogQLQuery: Story = {
    args: {
        insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/dataTableHogQL.json'),
    },
}

export const DataVisualizationHogQLQuery: Story = {
    args: {
        insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/dataVisualizationHogQL.json'),
    },
}

export const DataTableEventsQuery: Story = {
    args: {
        insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/dataTableEvents.json'),
    },
}
