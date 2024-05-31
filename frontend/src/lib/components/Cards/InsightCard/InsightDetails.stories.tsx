import { Meta, StoryFn } from '@storybook/react'

import { InsightModel } from '~/types'

import EXAMPLE_DATA_TABLE_NODE_EVENTS_QUERY from '../../../../mocks/fixtures/api/projects/team_id/insights/dataTableEvents.json'
import EXAMPLE_DATA_TABLE_NODE_HOGQL_QUERY from '../../../../mocks/fixtures/api/projects/team_id/insights/dataTableHogQL.json'
import EXAMPLE_FUNNEL from '../../../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json'
import EXAMPLE_LIFECYCLE from '../../../../mocks/fixtures/api/projects/team_id/insights/lifecycle.json'
import EXAMPLE_RETENTION from '../../../../mocks/fixtures/api/projects/team_id/insights/retention.json'
import EXAMPLE_STICKINESS from '../../../../mocks/fixtures/api/projects/team_id/insights/stickiness.json'
import EXAMPLE_TRENDS from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'
import EXAMPLE_TRENDS_MULTI from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsLineMulti.json'
import EXAMPLE_TRENDS_PIE from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsPie.json'
import EXAMPLE_TRENDS_TABLE from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsTable.json'
import EXAMPLE_TRENDS_HORIZONTAL_BAR from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsValue.json'
import EXAMPLE_TRENDS_WORLD_MAP from '../../../../mocks/fixtures/api/projects/team_id/insights/trendsWorldMap.json'
import EXAMPLE_PATHS from '../../../../mocks/fixtures/api/projects/team_id/insights/userPaths.json'
import { InsightDetails as InsightDetailsComponent } from './InsightDetails'

const meta: Meta = {
    title: 'Components/Cards/Insight Details',
    component: InsightDetailsComponent,
}
export default meta

const Template: StoryFn<{ insight: InsightModel }> = ({ insight }) => {
    return (
        <div className="bg-bg-light w-[24rem] p-4 rounded">
            <InsightDetailsComponent insight={insight} />
        </div>
    )
}

export const Trends = Template.bind({})
Trends.args = { insight: EXAMPLE_TRENDS as unknown as InsightModel }

export const TrendsMulti = Template.bind({})
TrendsMulti.args = { insight: EXAMPLE_TRENDS_MULTI as unknown as InsightModel }

export const TrendsHorizontalBar = Template.bind({})
TrendsHorizontalBar.args = { insight: EXAMPLE_TRENDS_HORIZONTAL_BAR as unknown as InsightModel }

export const TrendsTable = Template.bind({})
TrendsTable.args = { insight: EXAMPLE_TRENDS_TABLE as unknown as InsightModel }

export const TrendsPie = Template.bind({})
TrendsPie.args = { insight: EXAMPLE_TRENDS_PIE as unknown as InsightModel }

export const TrendsWorldMap = Template.bind({})
TrendsWorldMap.args = { insight: EXAMPLE_TRENDS_WORLD_MAP as unknown as InsightModel }

export const Funnel = Template.bind({})
Funnel.args = { insight: EXAMPLE_FUNNEL as unknown as InsightModel }

export const Retention = Template.bind({})
Retention.args = { insight: EXAMPLE_RETENTION as unknown as InsightModel }

export const Paths = Template.bind({})
Paths.args = { insight: EXAMPLE_PATHS as unknown as InsightModel }

export const Stickiness = Template.bind({})
Stickiness.args = { insight: EXAMPLE_STICKINESS as unknown as InsightModel }

export const Lifecycle = Template.bind({})
Lifecycle.args = { insight: EXAMPLE_LIFECYCLE as unknown as InsightModel }

export const DataTableHogQLQuery = Template.bind({})
DataTableHogQLQuery.args = { insight: EXAMPLE_DATA_TABLE_NODE_HOGQL_QUERY as unknown as InsightModel }

export const DataTableEventsQuery = Template.bind({})
DataTableEventsQuery.args = { insight: EXAMPLE_DATA_TABLE_NODE_EVENTS_QUERY as unknown as InsightModel }
