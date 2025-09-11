import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { ExportType } from '~/exporter/types'

import { Exporter } from '../Exporter'

type Story = StoryObj<typeof Exporter>
const meta: Meta<typeof Exporter> = {
    title: 'Exporter/Trends',
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

export const TrendsLineInsight: Story = Template.bind({})
TrendsLineInsight.args = { insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json') }
TrendsLineInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsLineInsightLegend: Story = Template.bind({})
TrendsLineInsightLegend.args = {
    insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'),
    legend: true,
}
TrendsLineInsightLegend.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsLineInsightDetailed: Story = Template.bind({})
TrendsLineInsightDetailed.args = {
    insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'),
    detailed: true,
}
TrendsLineInsightDetailed.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

/** This should not happen in the exporter, but if it does, it shouldn't error out - we want a clear message. */
export const TrendsLineInsightNoResults: Story = Template.bind({})
// @ts-expect-error
TrendsLineInsightNoResults.args = { insight: { ...TrendsLineInsight.args.insight, result: null } }
TrendsLineInsightNoResults.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsLineMultiInsight: Story = Template.bind({})
TrendsLineMultiInsight.args = {
    insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsLineMulti.json'),
}
TrendsLineMultiInsight.parameters = {
    mockDate: '2023-07-10',
}
TrendsLineMultiInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsLineBreakdownInsight: Story = Template.bind({})
TrendsLineBreakdownInsight.args = {
    insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdown.json'),
}
TrendsLineBreakdownInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsBarInsight: Story = Template.bind({})
TrendsBarInsight.args = { insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsBar.json') }
TrendsBarInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsBarBreakdownInsight: Story = Template.bind({})
TrendsBarBreakdownInsight.args = {
    insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsBarBreakdown.json'),
}
TrendsBarBreakdownInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsValueInsight: Story = Template.bind({})
TrendsValueInsight.args = { insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsValue.json') }
TrendsValueInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsValueBreakdownInsight: Story = Template.bind({})
TrendsValueBreakdownInsight.args = {
    insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsValueBreakdown.json'),
}
TrendsValueBreakdownInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsAreaInsight: Story = Template.bind({})
TrendsAreaInsight.args = { insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsArea.json') }
TrendsAreaInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsAreaBreakdownInsight: Story = Template.bind({})
TrendsAreaBreakdownInsight.args = {
    insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsAreaBreakdown.json'),
}
TrendsAreaBreakdownInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsNumberInsight: Story = Template.bind({})
TrendsNumberInsight.args = { insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsNumber.json') }
TrendsNumberInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsTableInsight: Story = Template.bind({})
TrendsTableInsight.args = { insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsTable.json') }

export const TrendsTableBreakdownInsight: Story = Template.bind({})
TrendsTableBreakdownInsight.args = {
    insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsTableBreakdown.json'),
}

export const TrendsPieInsight: Story = Template.bind({})
TrendsPieInsight.args = { insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsPie.json') }

export const TrendsPieInsightLegend: Story = Template.bind({})
TrendsPieInsightLegend.args = {
    insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsPie.json'),
    legend: true,
}

export const TrendsPieInsightDetailed: Story = Template.bind({})
TrendsPieInsightDetailed.args = {
    insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsPie.json'),
    detailed: true,
}

export const TrendsPieBreakdownInsight: Story = Template.bind({})
TrendsPieBreakdownInsight.args = {
    insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsPieBreakdown.json'),
}

export const TrendsWorldMapInsight: Story = Template.bind({})
TrendsWorldMapInsight.args = {
    insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsWorldMap.json'),
}
