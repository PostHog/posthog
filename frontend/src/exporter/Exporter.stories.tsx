import { useEffect } from 'react'
import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { Exporter } from './Exporter'
import { dashboard } from '~/exporter/__mocks__/Exporter.mocks'
import { ExportType } from '~/exporter/types'

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
TrendsLineInsight.args = { insight: require('../scenes/insights/__mocks__/trendsLine.json') }

export const TrendsLineBreakdownInsight: Story = Template.bind({})
TrendsLineBreakdownInsight.args = { insight: require('../scenes/insights/__mocks__/trendsLineBreakdown.json') }

export const TrendsBarInsight: Story = Template.bind({})
TrendsBarInsight.args = { insight: require('../scenes/insights/__mocks__/trendsBar.json') }

export const TrendsBarBreakdownInsight: Story = Template.bind({})
TrendsBarBreakdownInsight.args = { insight: require('../scenes/insights/__mocks__/trendsBarBreakdown.json') }

export const TrendsValueInsight: Story = Template.bind({})
TrendsValueInsight.args = { insight: require('../scenes/insights/__mocks__/trendsValue.json') }

export const TrendsValueBreakdownInsight: Story = Template.bind({})
TrendsValueBreakdownInsight.args = { insight: require('../scenes/insights/__mocks__/trendsValueBreakdown.json') }

export const TrendsAreaInsight: Story = Template.bind({})
TrendsAreaInsight.args = { insight: require('../scenes/insights/__mocks__/trendsArea.json') }

export const TrendsAreaBreakdownInsight: Story = Template.bind({})
TrendsAreaBreakdownInsight.args = { insight: require('../scenes/insights/__mocks__/trendsAreaBreakdown.json') }

export const TrendsNumberInsight: Story = Template.bind({})
TrendsNumberInsight.args = { insight: require('../scenes/insights/__mocks__/trendsNumber.json') }

export const TrendsTableInsight: Story = Template.bind({})
TrendsTableInsight.args = { insight: require('../scenes/insights/__mocks__/trendsTable.json') }

export const TrendsTableBreakdownInsight: Story = Template.bind({})
TrendsTableBreakdownInsight.args = { insight: require('../scenes/insights/__mocks__/trendsTableBreakdown.json') }

export const TrendsPieInsight: Story = Template.bind({})
TrendsPieInsight.args = { insight: require('../scenes/insights/__mocks__/trendsPie.json') }

export const TrendsPieBreakdownInsight: Story = Template.bind({})
TrendsPieBreakdownInsight.args = { insight: require('../scenes/insights/__mocks__/trendsPieBreakdown.json') }

export const TrendsWorldMapInsight: Story = Template.bind({})
TrendsWorldMapInsight.args = { insight: require('../scenes/insights/__mocks__/trendsWorldMap.json') }

export const FunnelLeftToRightInsight: Story = Template.bind({})
FunnelLeftToRightInsight.args = { insight: require('../scenes/insights/__mocks__/funnelLeftToRight.json') }

export const FunnelLeftToRightBreakdownInsight: Story = Template.bind({})
FunnelLeftToRightBreakdownInsight.args = {
    insight: require('../scenes/insights/__mocks__/funnelLeftToRightBreakdown.json'),
}

export const FunnelTopToBottomInsight: Story = Template.bind({})
FunnelTopToBottomInsight.args = { insight: require('../scenes/insights/__mocks__/funnelTopToBottom.json') }

export const FunnelTopToBottomBreakdownInsight: Story = Template.bind({})
FunnelTopToBottomBreakdownInsight.args = {
    insight: require('../scenes/insights/__mocks__/funnelTopToBottomBreakdown.json'),
}

export const FunnelHistoricalTrendsInsight: Story = Template.bind({})
FunnelHistoricalTrendsInsight.args = { insight: require('../scenes/insights/__mocks__/funnelHistoricalTrends.json') }

export const FunnelTimeToConvertInsight: Story = Template.bind({})
FunnelTimeToConvertInsight.args = { insight: require('../scenes/insights/__mocks__/funnelTimeToConvert.json') }

export const RetentionInsight: Story = Template.bind({})
RetentionInsight.args = { insight: require('../scenes/insights/__mocks__/retention.json') }

export const RetentionBreakdownInsight: Story = Template.bind({})
RetentionBreakdownInsight.args = { insight: require('../scenes/insights/__mocks__/retentionBreakdown.json') }

export const LifecycleInsight: Story = Template.bind({})
LifecycleInsight.args = { insight: require('../scenes/insights/__mocks__/lifecycle.json') }

export const StickinessInsight: Story = Template.bind({})
StickinessInsight.args = { insight: require('../scenes/insights/__mocks__/stickiness.json') }

export const UserPathsInsight: Story = Template.bind({})
UserPathsInsight.args = { insight: require('../scenes/insights/__mocks__/userPaths.json') }

export const Dashboard: Story = Template.bind({})
Dashboard.args = { dashboard }
