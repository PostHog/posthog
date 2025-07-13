import { Meta, StoryFn } from '@storybook/react'

import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { InsightModel } from '~/types'

import trendsLineInsight from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json?url'
import trendsLineMultiInsight from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsLineMulti.json?url'
import trendsValueInsight from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsValue.json?url'
import trendsTableInsight from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsTable.json?url'
import trendsPieInsight from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsPie.json?url'
import trendsWorldMapInsight from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsWorldMap.json?url'
import funnelLeftToRightInsight from '../../../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json?url'
import retentionInsight from '../../../../mocks/fixtures/api/projects/team_id/insights/retention.json?url'
import userPathsInsight from '../../../../mocks/fixtures/api/projects/team_id/insights/userPaths.json?url'
import stickinessInsight from '../../../../mocks/fixtures/api/projects/team_id/insights/stickiness.json?url'
import lifecycleInsight from '../../../../mocks/fixtures/api/projects/team_id/insights/lifecycle.json?url'
import dataTableHogQLInsight from '../../../../mocks/fixtures/api/projects/team_id/insights/dataTableHogQL.json?url'
import dataVisualizationHogQLInsight from '../../../../mocks/fixtures/api/projects/team_id/insights/dataVisualizationHogQL.json?url'
import dataTableEventsInsight from '../../../../mocks/fixtures/api/projects/team_id/insights/dataTableEvents.json?url'
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

export const Trends: StoryFn<{ insight: InsightModel }> = Template.bind({})
Trends.args = {
    insight: trendsLineInsight,
}

export const TrendsMulti: StoryFn<{ insight: InsightModel }> = Template.bind({})
TrendsMulti.args = {
    insight: trendsLineMultiInsight,
}

export const TrendsHorizontalBar: StoryFn<{ insight: InsightModel }> = Template.bind({})
TrendsHorizontalBar.args = {
    insight: trendsValueInsight,
}

export const TrendsTable: StoryFn<{ insight: InsightModel }> = Template.bind({})
TrendsTable.args = { insight: trendsTableInsight }

export const TrendsPie: StoryFn<{ insight: InsightModel }> = Template.bind({})
TrendsPie.args = { insight: trendsPieInsight }

export const TrendsWorldMap: StoryFn<{ insight: InsightModel }> = Template.bind({})
TrendsWorldMap.args = {
    insight: trendsWorldMapInsight,
}

export const Funnel: StoryFn<{ insight: InsightModel }> = Template.bind({})
Funnel.args = {
    insight: funnelLeftToRightInsight,
}

export const Retention: StoryFn<{ insight: InsightModel }> = Template.bind({})
Retention.args = {
    insight: retentionInsight,
}

export const Paths: StoryFn<{ insight: InsightModel }> = Template.bind({})
Paths.args = {
    insight: userPathsInsight,
}

export const Stickiness: StoryFn<{ insight: InsightModel }> = Template.bind({})
Stickiness.args = { insight: stickinessInsight }

export const Lifecycle: StoryFn<{ insight: InsightModel }> = Template.bind({})
Lifecycle.args = {
    insight: lifecycleInsight,
}

export const DataTableHogQLQuery: StoryFn<{ insight: InsightModel }> = Template.bind({})
DataTableHogQLQuery.args = {
    insight: dataTableHogQLInsight,
}

export const DataVisualizationHogQLQuery: StoryFn<{ insight: InsightModel }> = Template.bind({})
DataVisualizationHogQLQuery.args = {
    insight: dataVisualizationHogQLInsight,
}

export const DataTableEventsQuery: StoryFn<{ insight: InsightModel }> = Template.bind({})
DataTableEventsQuery.args = {
    insight: dataTableEventsInsight,
}
