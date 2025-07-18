import { Meta, StoryFn } from '@storybook/react'

import { getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { InsightModel } from '~/types'

import trendsLineInsightData from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'
import trendsLineMultiInsightData from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsLineMulti.json'
import trendsValueInsightData from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsValue.json'
import trendsTableInsightData from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsTable.json'
import trendsPieInsightData from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsPie.json'
import trendsWorldMapInsightData from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsWorldMap.json'
import funnelLeftToRightInsightData from '../../../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json'
import retentionInsightData from '../../../../mocks/fixtures/api/projects/team_id/insights/retention.json'
import userPathsInsightData from '../../../../mocks/fixtures/api/projects/team_id/insights/userPaths.json'
import stickinessInsightData from '../../../../mocks/fixtures/api/projects/team_id/insights/stickiness.json'
import lifecycleInsightData from '../../../../mocks/fixtures/api/projects/team_id/insights/lifecycle.json'
import dataTableHogQLInsightData from '../../../../mocks/fixtures/api/projects/team_id/insights/dataTableHogQL.json'
import dataVisualizationHogQLInsightData from '../../../../mocks/fixtures/api/projects/team_id/insights/dataVisualizationHogQL.json'
import dataTableEventsInsightData from '../../../../mocks/fixtures/api/projects/team_id/insights/dataTableEvents.json'

import { InsightDetails as InsightDetailsComponent } from './InsightDetails'

const trendsLineInsight = trendsLineInsightData as unknown as any
const trendsLineMultiInsight = trendsLineMultiInsightData as unknown as any
const trendsValueInsight = trendsValueInsightData as unknown as any
const trendsTableInsight = trendsTableInsightData as unknown as any
const trendsPieInsight = trendsPieInsightData as unknown as any
const trendsWorldMapInsight = trendsWorldMapInsightData as unknown as any
const funnelLeftToRightInsight = funnelLeftToRightInsightData as unknown as any
const retentionInsight = retentionInsightData as unknown as any
const userPathsInsight = userPathsInsightData as unknown as any
const stickinessInsight = stickinessInsightData as unknown as any
const lifecycleInsight = lifecycleInsightData as unknown as any
const dataTableHogQLInsight = dataTableHogQLInsightData as unknown as any
const dataVisualizationHogQLInsight = dataVisualizationHogQLInsightData as unknown as any
const dataTableEventsInsight = dataTableEventsInsightData as unknown as any

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
