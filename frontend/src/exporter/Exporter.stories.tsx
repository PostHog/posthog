import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { dashboard } from '~/exporter/__mocks__/Exporter.mocks'
import { ExportType } from '~/exporter/types'

import { Exporter } from './Exporter'

type Story = StoryObj<typeof Exporter>
const meta: Meta<typeof Exporter> = {
    title: 'Exporter/Exporter',
    component: Exporter,
    args: {
        type: ExportType.Embed,
        whitelabel: false,
        noHeader: false,
        legend: false,
        detailed: false,
    },
    parameters: {
        testOptions: {
            snapshotBrowsers: ['chromium'],
        },
        mockDate: '2023-02-01',
        viewMode: 'story',
    },
}

export default meta

const Template: StoryFn<typeof Exporter> = (props) => {
    useEffect(() => {
        document.body.className = ''
        document.documentElement.className = `export-type-${props.type}`
    }, [props.type])
    return (
        <div className={`storybook-export-type-${props.type} p-4`}>
            <Exporter {...props} />
        </div>
    )
}

export const TrendsLineInsight: Story = Template.bind({})
TrendsLineInsight.args = { insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsLine.json') }
TrendsLineInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsLineInsightLegend: Story = Template.bind({})
TrendsLineInsightLegend.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'),
    legend: true,
}

export const TrendsLineInsightDetailed: Story = Template.bind({})
TrendsLineInsightDetailed.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'),
    detailed: true,
}

/** This should not happen in the exporter, but if it does, it shouldn't error out - we want a clear message. */
export const TrendsLineInsightNoResults: Story = Template.bind({})
// @ts-expect-error
TrendsLineInsightNoResults.args = { insight: { ...TrendsLineInsight.args.insight, result: null } }

export const TrendsLineMultiInsight: Story = Template.bind({})
TrendsLineMultiInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsLineMulti.json'),
}
TrendsLineMultiInsight.parameters = {
    mockDate: '2023-07-10',
}
TrendsLineMultiInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsLineBreakdownInsight: Story = Template.bind({})
TrendsLineBreakdownInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdown.json'),
}
TrendsLineBreakdownInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsBarInsight: Story = Template.bind({})
TrendsBarInsight.args = { insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsBar.json') }
TrendsBarInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsBarBreakdownInsight: Story = Template.bind({})
TrendsBarBreakdownInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsBarBreakdown.json'),
}
TrendsBarBreakdownInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsValueInsight: Story = Template.bind({})
TrendsValueInsight.args = { insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsValue.json') }
TrendsValueInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsValueBreakdownInsight: Story = Template.bind({})
TrendsValueBreakdownInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsValueBreakdown.json'),
}
TrendsValueBreakdownInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsAreaInsight: Story = Template.bind({})
TrendsAreaInsight.args = { insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsArea.json') }
TrendsAreaInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsAreaBreakdownInsight: Story = Template.bind({})
TrendsAreaBreakdownInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsAreaBreakdown.json'),
}
TrendsAreaBreakdownInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsNumberInsight: Story = Template.bind({})
TrendsNumberInsight.args = { insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsNumber.json') }
TrendsNumberInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsTableInsight: Story = Template.bind({})
TrendsTableInsight.args = { insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsTable.json') }

export const TrendsTableBreakdownInsight: Story = Template.bind({})
TrendsTableBreakdownInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsTableBreakdown.json'),
}

export const TrendsPieInsight: Story = Template.bind({})
TrendsPieInsight.args = { insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsPie.json') }

export const TrendsPieInsightLegend: Story = Template.bind({})
TrendsPieInsightLegend.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsPie.json'),
    legend: true,
}

export const TrendsPieInsightDetailed: Story = Template.bind({})
TrendsPieInsightDetailed.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsPie.json'),
    detailed: true,
}

export const TrendsPieBreakdownInsight: Story = Template.bind({})
TrendsPieBreakdownInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsPieBreakdown.json'),
}

export const TrendsWorldMapInsight: Story = Template.bind({})
TrendsWorldMapInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsWorldMap.json'),
}

export const FunnelLeftToRightInsight: Story = Template.bind({})
FunnelLeftToRightInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json'),
}

/** This should not happen in the exporter, but if it does, it shouldn't error out - we want a clear message. */
export const FunnelLeftToRightInsightNoResults: Story = Template.bind({})
// @ts-expect-error
FunnelLeftToRightInsightNoResults.args = { insight: { ...FunnelLeftToRightInsight.args.insight, result: null } }

export const FunnelLeftToRightBreakdownInsight: Story = Template.bind({})
FunnelLeftToRightBreakdownInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRightBreakdown.json'),
}

export const FunnelTopToBottomInsight: Story = Template.bind({})
FunnelTopToBottomInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json'),
}
/** This should not happen in the exporter, but if it does, it shouldn't error out - we want a clear message. */
export const FunnelTopToBottomInsightNoResults: Story = Template.bind({})
// @ts-expect-error
FunnelTopToBottomInsightNoResults.args = { insight: { ...FunnelTopToBottomInsight.args.insight, result: null } }

export const FunnelTopToBottomBreakdownInsight: Story = Template.bind({})
FunnelTopToBottomBreakdownInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottomBreakdown.json'),
}

export const FunnelHistoricalTrendsInsight: Story = Template.bind({})
FunnelHistoricalTrendsInsight.tags = ['autodocs', 'test-skip']
FunnelHistoricalTrendsInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/funnelHistoricalTrends.json'),
}

export const FunnelTimeToConvertInsight: Story = Template.bind({})
FunnelTimeToConvertInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/funnelTimeToConvert.json'),
}

export const RetentionInsight: Story = Template.bind({})
RetentionInsight.args = { insight: require('../mocks/fixtures/api/projects/team_id/insights/retention.json') }

export const RetentionBreakdownInsight: Story = Template.bind({})
RetentionBreakdownInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/retentionBreakdown.json'),
}

export const LifecycleInsight: Story = Template.bind({})
LifecycleInsight.args = { insight: require('../mocks/fixtures/api/projects/team_id/insights/lifecycle.json') }
LifecycleInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const StickinessInsight: Story = Template.bind({})
StickinessInsight.args = { insight: require('../mocks/fixtures/api/projects/team_id/insights/stickiness.json') }
StickinessInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const UserPathsInsight: Story = Template.bind({})
UserPathsInsight.args = { insight: require('../mocks/fixtures/api/projects/team_id/insights/userPaths.json') }
UserPathsInsight.tags = ['test-skip'] // FIXME: flaky tests, most likely due to resize observer changes

export const Dashboard: Story = Template.bind({})
Dashboard.args = { dashboard }

export const EventTableInsight: Story = Template.bind({})
EventTableInsight.args = { insight: require('../mocks/fixtures/api/projects/team_id/insights/dataTableEvents.json') }

/** This should not happen in the exporter, but if it does, it shouldn't error out - we want a clear message. */
export const EventTableInsightNoResults: Story = Template.bind({})
// @ts-expect-error
EventTableInsightNoResults.args = { insight: { ...EventTableInsight.args.insight, result: null } }

export const SQLInsight: Story = Template.bind({})
SQLInsight.args = { insight: require('../mocks/fixtures/api/projects/team_id/insights/dataTableHogQL.json') }

/** This should not happen in the exporter, but if it does, it shouldn't error out - we want a clear message. */
export const SQLInsightNoResults: Story = Template.bind({})
// @ts-expect-error
SQLInsightNoResults.args = { insight: { ...SQLInsight.args.insight, result: null } }
