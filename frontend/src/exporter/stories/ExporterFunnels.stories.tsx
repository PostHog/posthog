import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { ExportType } from '~/exporter/types'

import { Exporter } from '../Exporter'

type Story = StoryObj<typeof Exporter>
const meta: Meta<typeof Exporter> = {
    title: 'Exporter/Funnels',
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
    tags: [], // Omit 'autodocs', as it's broken with Exporter
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

export const FunnelLeftToRightInsight: Story = Template.bind({})
FunnelLeftToRightInsight.args = {
    insight: require('../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json'),
}

/** This should not happen in the exporter, but if it does, it shouldn't error out - we want a clear message. */
export const FunnelLeftToRightInsightNoResults: Story = Template.bind({})
// @ts-expect-error
FunnelLeftToRightInsightNoResults.args = { insight: { ...FunnelLeftToRightInsight.args.insight, result: null } }

export const FunnelLeftToRightBreakdownInsight: Story = Template.bind({})
FunnelLeftToRightBreakdownInsight.args = {
    insight: require('../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRightBreakdown.json'),
}

export const FunnelTopToBottomInsight: Story = Template.bind({})
FunnelTopToBottomInsight.args = {
    insight: require('../../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json'),
}
/** This should not happen in the exporter, but if it does, it shouldn't error out - we want a clear message. */
export const FunnelTopToBottomInsightNoResults: Story = Template.bind({})
// @ts-expect-error
FunnelTopToBottomInsightNoResults.args = { insight: { ...FunnelTopToBottomInsight.args.insight, result: null } }

export const FunnelTopToBottomBreakdownInsight: Story = Template.bind({})
FunnelTopToBottomBreakdownInsight.args = {
    insight: require('../../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottomBreakdown.json'),
}

export const FunnelHistoricalTrendsInsight: Story = Template.bind({})
FunnelHistoricalTrendsInsight.tags = ['test-skip']
FunnelHistoricalTrendsInsight.args = {
    insight: require('../../mocks/fixtures/api/projects/team_id/insights/funnelHistoricalTrends.json'),
}

export const FunnelTimeToConvertInsight: Story = Template.bind({})
FunnelTimeToConvertInsight.args = {
    insight: require('../../mocks/fixtures/api/projects/team_id/insights/funnelTimeToConvert.json'),
}
