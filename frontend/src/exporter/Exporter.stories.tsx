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

export const TrendsLineInsight: Story = {
    render: Template,
    args: { insight: require('../scenes/insights/__mocks__/trendsLine.json') },
}

export const TrendsLineBreakdownInsight: Story = {
    render: Template,
    args: { insight: require('../scenes/insights/__mocks__/trendsLineBreakdown.json') },
}

export const TrendsBarInsight: Story = {
    render: Template,
    args: { insight: require('../scenes/insights/__mocks__/trendsBar.json') },
}

export const TrendsBarBreakdownInsight: Story = {
    render: Template,
    args: { insight: require('../scenes/insights/__mocks__/trendsBarBreakdown.json') },
}

export const TrendsValueInsight: Story = {
    render: Template,
    args: { insight: require('../scenes/insights/__mocks__/trendsValue.json') },
}

export const TrendsValueBreakdownInsight: Story = {
    render: Template,
    args: { insight: require('../scenes/insights/__mocks__/trendsValueBreakdown.json') },
}

export const TrendsAreaInsight: Story = {
    render: Template,
    args: { insight: require('../scenes/insights/__mocks__/trendsArea.json') },
}

export const TrendsAreaBreakdownInsight: Story = {
    render: Template,
    args: { insight: require('../scenes/insights/__mocks__/trendsAreaBreakdown.json') },
}

export const TrendsNumberInsight: Story = {
    render: Template,
    args: { insight: require('../scenes/insights/__mocks__/trendsNumber.json') },
}

export const TrendsTableInsight: Story = {
    render: Template,
    args: { insight: require('../scenes/insights/__mocks__/trendsTable.json') },
}

export const TrendsTableBreakdownInsight: Story = {
    render: Template,
    args: { insight: require('../scenes/insights/__mocks__/trendsTableBreakdown.json') },
}

export const TrendsPieInsight: Story = {
    render: Template,
    args: { insight: require('../scenes/insights/__mocks__/trendsPie.json') },
}

export const TrendsPieBreakdownInsight: Story = {
    render: Template,
    args: { insight: require('../scenes/insights/__mocks__/trendsPieBreakdown.json') },
}

export const TrendsWorldMapInsight: Story = {
    render: Template,
    args: { insight: require('../scenes/insights/__mocks__/trendsWorldMap.json') },
}

export const FunnelLeftToRightInsight: Story = {
    render: Template,
    args: { insight: require('../scenes/insights/__mocks__/funnelLeftToRight.json') },
}

export const FunnelLeftToRightBreakdownInsight: Story = {
    render: Template,

    args: {
        insight: require('../scenes/insights/__mocks__/funnelLeftToRightBreakdown.json'),
    },
}

export const FunnelTopToBottomInsight: Story = {
    render: Template,
    args: { insight: require('../scenes/insights/__mocks__/funnelTopToBottom.json') },
}

export const FunnelTopToBottomBreakdownInsight: Story = {
    render: Template,

    args: {
        insight: require('../scenes/insights/__mocks__/funnelTopToBottomBreakdown.json'),
    },
}

export const FunnelHistoricalTrendsInsight: Story = {
    render: Template,
    args: { insight: require('../scenes/insights/__mocks__/funnelHistoricalTrends.json') },
}

export const FunnelTimeToConvertInsight: Story = {
    render: Template,
    args: { insight: require('../scenes/insights/__mocks__/funnelTimeToConvert.json') },
}

export const RetentionInsight: Story = {
    render: Template,
    args: { insight: require('../scenes/insights/__mocks__/retention.json') },
}

export const RetentionBreakdownInsight: Story = {
    render: Template,
    args: { insight: require('../scenes/insights/__mocks__/retentionBreakdown.json') },
}

export const LifecycleInsight: Story = {
    render: Template,
    args: { insight: require('../scenes/insights/__mocks__/lifecycle.json') },
}

export const StickinessInsight: Story = {
    render: Template,
    args: { insight: require('../scenes/insights/__mocks__/stickiness.json') },
}

export const UserPathsInsight: Story = {
    render: Template,
    args: { insight: require('../scenes/insights/__mocks__/userPaths.json') },
}

export const Dashboard: Story = {
    render: Template,
    args: { dashboard },
}
