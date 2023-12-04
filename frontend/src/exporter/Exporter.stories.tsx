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

export const TrendsLineMultiInsight: Story = Template.bind({})
TrendsLineMultiInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsLineMulti.json'),
}
TrendsLineMultiInsight.parameters = {
    mockDate: '2023-07-10',
}

export const TrendsLineBreakdownInsight: Story = Template.bind({})
TrendsLineBreakdownInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdown.json'),
}

export const TrendsBarInsight: Story = Template.bind({})
TrendsBarInsight.args = { insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsBar.json') }

export const TrendsBarBreakdownInsight: Story = Template.bind({})
TrendsBarBreakdownInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsBarBreakdown.json'),
}

export const TrendsValueInsight: Story = Template.bind({})
TrendsValueInsight.args = { insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsValue.json') }

export const TrendsValueBreakdownInsight: Story = Template.bind({})
TrendsValueBreakdownInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsValueBreakdown.json'),
}

export const TrendsAreaInsight: Story = Template.bind({})
TrendsAreaInsight.args = { insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsArea.json') }

export const TrendsAreaBreakdownInsight: Story = Template.bind({})
TrendsAreaBreakdownInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsAreaBreakdown.json'),
}

export const TrendsNumberInsight: Story = Template.bind({})
TrendsNumberInsight.args = { insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsNumber.json') }

export const TrendsTableInsight: Story = Template.bind({})
TrendsTableInsight.args = { insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsTable.json') }

export const TrendsTableBreakdownInsight: Story = Template.bind({})
TrendsTableBreakdownInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsTableBreakdown.json'),
}

export const TrendsPieInsight: Story = Template.bind({})
TrendsPieInsight.args = { insight: require('../mocks/fixtures/api/projects/team_id/insights/trendsPie.json') }

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

export const FunnelLeftToRightBreakdownInsight: Story = Template.bind({})
FunnelLeftToRightBreakdownInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRightBreakdown.json'),
}

export const FunnelTopToBottomInsight: Story = Template.bind({})
FunnelTopToBottomInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json'),
}

export const FunnelTopToBottomBreakdownInsight: Story = Template.bind({})
FunnelTopToBottomBreakdownInsight.args = {
    insight: require('../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottomBreakdown.json'),
}

export const FunnelHistoricalTrendsInsight: Story = Template.bind({})
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

export const StickinessInsight: Story = Template.bind({})
StickinessInsight.args = { insight: require('../mocks/fixtures/api/projects/team_id/insights/stickiness.json') }

export const UserPathsInsight: Story = Template.bind({})
UserPathsInsight.args = { insight: require('../mocks/fixtures/api/projects/team_id/insights/userPaths.json') }

export const Dashboard: Story = Template.bind({})
Dashboard.args = { dashboard }
