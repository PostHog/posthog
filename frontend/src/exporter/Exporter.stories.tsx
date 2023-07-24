import { useEffect } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { Exporter } from './Exporter'
import { dashboard } from '~/exporter/__mocks__/Exporter.mocks'

export default {
    title: 'Exporter/Exporter',
    component: Exporter,
    args: {
        type: 'embed',
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
} as ComponentMeta<typeof Exporter>

const Template: ComponentStory<typeof Exporter> = (props) => {
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

export const TrendsLineInsight = Template.bind({})
TrendsLineInsight.args = { insight: require('../scenes/insights/__mocks__/trendsLine.json') }

export const TrendsLineBreakdownInsight = Template.bind({})
TrendsLineBreakdownInsight.args = { insight: require('../scenes/insights/__mocks__/trendsLineBreakdown.json') }

export const TrendsBarInsight = Template.bind({})
TrendsBarInsight.args = { insight: require('../scenes/insights/__mocks__/trendsBar.json') }

export const TrendsBarBreakdownInsight = Template.bind({})
TrendsBarBreakdownInsight.args = { insight: require('../scenes/insights/__mocks__/trendsBarBreakdown.json') }

export const TrendsValueInsight = Template.bind({})
TrendsValueInsight.args = { insight: require('../scenes/insights/__mocks__/trendsValue.json') }

export const TrendsValueBreakdownInsight = Template.bind({})
TrendsValueBreakdownInsight.args = { insight: require('../scenes/insights/__mocks__/trendsValueBreakdown.json') }

export const TrendsAreaInsight = Template.bind({})
TrendsAreaInsight.args = { insight: require('../scenes/insights/__mocks__/trendsArea.json') }

export const TrendsAreaBreakdownInsight = Template.bind({})
TrendsAreaBreakdownInsight.args = { insight: require('../scenes/insights/__mocks__/trendsAreaBreakdown.json') }

export const TrendsNumberInsight = Template.bind({})
TrendsNumberInsight.args = { insight: require('../scenes/insights/__mocks__/trendsNumber.json') }

export const TrendsTableInsight = Template.bind({})
TrendsTableInsight.args = { insight: require('../scenes/insights/__mocks__/trendsTable.json') }

export const TrendsTableBreakdownInsight = Template.bind({})
TrendsTableBreakdownInsight.args = { insight: require('../scenes/insights/__mocks__/trendsTableBreakdown.json') }

export const TrendsPieInsight = Template.bind({})
TrendsPieInsight.args = { insight: require('../scenes/insights/__mocks__/trendsPie.json') }

export const TrendsPieBreakdownInsight = Template.bind({})
TrendsPieBreakdownInsight.args = { insight: require('../scenes/insights/__mocks__/trendsPieBreakdown.json') }

export const TrendsWorldMapInsight = Template.bind({})
TrendsWorldMapInsight.args = { insight: require('../scenes/insights/__mocks__/trendsWorldMap.json') }

export const FunnelLeftToRightInsight = Template.bind({})
FunnelLeftToRightInsight.args = { insight: require('../scenes/insights/__mocks__/funnelLeftToRight.json') }

export const FunnelLeftToRightBreakdownInsight = Template.bind({})
FunnelLeftToRightBreakdownInsight.args = {
    insight: require('../scenes/insights/__mocks__/funnelLeftToRightBreakdown.json'),
}

export const FunnelTopToBottomInsight = Template.bind({})
FunnelTopToBottomInsight.args = { insight: require('../scenes/insights/__mocks__/funnelTopToBottom.json') }

export const FunnelTopToBottomBreakdownInsight = Template.bind({})
FunnelTopToBottomBreakdownInsight.args = {
    insight: require('../scenes/insights/__mocks__/funnelTopToBottomBreakdown.json'),
}

export const FunnelHistoricalTrendsInsight = Template.bind({})
FunnelHistoricalTrendsInsight.args = { insight: require('../scenes/insights/__mocks__/funnelHistoricalTrends.json') }

export const FunnelTimeToConvertInsight = Template.bind({})
FunnelTimeToConvertInsight.args = { insight: require('../scenes/insights/__mocks__/funnelTimeToConvert.json') }

export const RetentionInsight = Template.bind({})
RetentionInsight.args = { insight: require('../scenes/insights/__mocks__/retention.json') }

export const RetentionBreakdownInsight = Template.bind({})
RetentionBreakdownInsight.args = { insight: require('../scenes/insights/__mocks__/retentionBreakdown.json') }

export const LifecycleInsight = Template.bind({})
LifecycleInsight.args = { insight: require('../scenes/insights/__mocks__/lifecycle.json') }

export const StickinessInsight = Template.bind({})
StickinessInsight.args = { insight: require('../scenes/insights/__mocks__/stickiness.json') }

export const UserPathsInsight = Template.bind({})
UserPathsInsight.args = { insight: require('../scenes/insights/__mocks__/userPaths.json') }

export const Dashboard = Template.bind({})
Dashboard.args = { dashboard }
