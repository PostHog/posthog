import { Meta, StoryFn } from '@storybook/react'

import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { InsightModel } from '~/types'

import { InsightDetails as InsightDetailsComponent } from './InsightDetails'

const meta: Meta = {
    title: 'Components/Cards/Insight Details',
    component: InsightDetailsComponent,
}
export default meta

const Template: StoryFn<{ insight: InsightModel }> = ({ insight: legacyInsight }) => {
    const insight = getQueryBasedInsightModel(legacyInsight)
    return (
        <div className="bg-surface-primary w-[24rem] p-4 rounded">
            <InsightDetailsComponent query={insight.query} footerInfo={insight} />
        </div>
    )
}

export const Trends = Template.bind({})
Trends.args = {
    insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'),
}

export const TrendsMulti = Template.bind({})
TrendsMulti.args = {
    insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsLineMulti.json'),
}

export const TrendsHorizontalBar = Template.bind({})
TrendsHorizontalBar.args = {
    insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsValue.json'),
}

export const TrendsTable = Template.bind({})
TrendsTable.args = { insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsTable.json') }

export const TrendsPie = Template.bind({})
TrendsPie.args = { insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsPie.json') }

export const TrendsWorldMap = Template.bind({})
TrendsWorldMap.args = {
    insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsWorldMap.json'),
}

export const Funnel = Template.bind({})
Funnel.args = {
    insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json'),
}

export const Retention = Template.bind({})
Retention.args = {
    insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/retention.json'),
}

export const Paths = Template.bind({})
Paths.args = {
    insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/userPaths.json'),
}

export const Stickiness = Template.bind({})
Stickiness.args = { insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/stickiness.json') }

export const Lifecycle = Template.bind({})
Lifecycle.args = {
    insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/lifecycle.json'),
}

export const DataTableHogQLQuery = Template.bind({})
DataTableHogQLQuery.args = {
    insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/dataTableHogQL.json'),
}

export const DataVisualizationHogQLQuery = Template.bind({})
DataVisualizationHogQLQuery.args = {
    insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/dataVisualizationHogQL.json'),
}

export const DataTableEventsQuery = Template.bind({})
DataTableEventsQuery.args = {
    insight: require('../../../../mocks/fixtures/api/projects/team_id/insights/dataTableEvents.json'),
}
