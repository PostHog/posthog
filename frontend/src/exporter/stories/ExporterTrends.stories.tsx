import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { ExportType } from '~/exporter/types'
import trendsLineInsightData from '../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'
import trendsLineMultiInsightData from '../../mocks/fixtures/api/projects/team_id/insights/trendsLineMulti.json'
import trendsLineBreakdownInsightData from '../../mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdown.json'
import trendsBarInsightData from '../../mocks/fixtures/api/projects/team_id/insights/trendsBar.json'
import trendsBarBreakdownInsightData from '../../mocks/fixtures/api/projects/team_id/insights/trendsBarBreakdown.json'
import trendsValueInsightData from '../../mocks/fixtures/api/projects/team_id/insights/trendsValue.json'
import trendsValueBreakdownInsightData from '../../mocks/fixtures/api/projects/team_id/insights/trendsValueBreakdown.json'
import trendsAreaInsightData from '../../mocks/fixtures/api/projects/team_id/insights/trendsArea.json'
import trendsAreaBreakdownInsightData from '../../mocks/fixtures/api/projects/team_id/insights/trendsAreaBreakdown.json'
import trendsNumberInsightData from '../../mocks/fixtures/api/projects/team_id/insights/trendsNumber.json'
import trendsTableInsightData from '../../mocks/fixtures/api/projects/team_id/insights/trendsTable.json'
import trendsTableBreakdownInsightData from '../../mocks/fixtures/api/projects/team_id/insights/trendsTableBreakdown.json'
import trendsPieInsightData from '../../mocks/fixtures/api/projects/team_id/insights/trendsPie.json'
import trendsPieBreakdownInsightData from '../../mocks/fixtures/api/projects/team_id/insights/trendsPieBreakdown.json'
import trendsWorldMapInsightData from '../../mocks/fixtures/api/projects/team_id/insights/trendsWorldMap.json'

import { Exporter } from '../Exporter'
import { InsightModel } from '~/types'

const trendsLineInsight = trendsLineInsightData as unknown as InsightModel
const trendsLineMultiInsight = trendsLineMultiInsightData as unknown as InsightModel
const trendsLineBreakdownInsight = trendsLineBreakdownInsightData as unknown as InsightModel
const trendsBarInsight = trendsBarInsightData as unknown as InsightModel
const trendsBarBreakdownInsight = trendsBarBreakdownInsightData as unknown as InsightModel
const trendsValueInsight = trendsValueInsightData as unknown as InsightModel
const trendsValueBreakdownInsight = trendsValueBreakdownInsightData as unknown as InsightModel
const trendsAreaInsight = trendsAreaInsightData as unknown as InsightModel
const trendsAreaBreakdownInsight = trendsAreaBreakdownInsightData as unknown as InsightModel
const trendsNumberInsight = trendsNumberInsightData as unknown as InsightModel
const trendsTableInsight = trendsTableInsightData as unknown as InsightModel
const trendsTableBreakdownInsight = trendsTableBreakdownInsightData as unknown as InsightModel
const trendsPieInsight = trendsPieInsightData as unknown as InsightModel
const trendsPieBreakdownInsight = trendsPieBreakdownInsightData as unknown as InsightModel
const trendsWorldMapInsight = trendsWorldMapInsightData as unknown as InsightModel

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
TrendsLineInsight.args = { insight: trendsLineInsight }
TrendsLineInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsLineInsightLegend: Story = Template.bind({})
TrendsLineInsightLegend.args = {
    insight: trendsLineInsight,
    legend: true,
}
TrendsLineInsightLegend.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsLineInsightDetailed: Story = Template.bind({})
TrendsLineInsightDetailed.args = {
    insight: trendsLineInsight,
    detailed: true,
}
TrendsLineInsightDetailed.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

/** This should not happen in the exporter, but if it does, it shouldn't error out - we want a clear message. */
export const TrendsLineInsightNoResults: Story = Template.bind({})

TrendsLineInsightNoResults.args = { insight: { ...trendsLineInsight, result: null } }
TrendsLineInsightNoResults.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsLineMultiInsight: Story = Template.bind({})
TrendsLineMultiInsight.args = {
    insight: trendsLineMultiInsight,
}
TrendsLineMultiInsight.parameters = {
    mockDate: '2023-07-10',
}
TrendsLineMultiInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsLineBreakdownInsight: Story = Template.bind({})
TrendsLineBreakdownInsight.args = {
    insight: trendsLineBreakdownInsight,
}
TrendsLineBreakdownInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsBarInsight: Story = Template.bind({})
TrendsBarInsight.args = { insight: trendsBarInsight }
TrendsBarInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsBarBreakdownInsight: Story = Template.bind({})
TrendsBarBreakdownInsight.args = {
    insight: trendsBarBreakdownInsight,
}
TrendsBarBreakdownInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsValueInsight: Story = Template.bind({})
TrendsValueInsight.args = { insight: trendsValueInsight }
TrendsValueInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsValueBreakdownInsight: Story = Template.bind({})
TrendsValueBreakdownInsight.args = {
    insight: trendsValueBreakdownInsight,
}
TrendsValueBreakdownInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsAreaInsight: Story = Template.bind({})
TrendsAreaInsight.args = { insight: trendsAreaInsight }
TrendsAreaInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsAreaBreakdownInsight: Story = Template.bind({})
TrendsAreaBreakdownInsight.args = {
    insight: trendsAreaBreakdownInsight,
}
TrendsAreaBreakdownInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsNumberInsight: Story = Template.bind({})
TrendsNumberInsight.args = { insight: trendsNumberInsight }
TrendsNumberInsight.tags = ['test-skip'] // doesn't produce a helpful reference image, as canvas can't be captured

export const TrendsTableInsight: Story = Template.bind({})
TrendsTableInsight.args = { insight: trendsTableInsight }

export const TrendsTableBreakdownInsight: Story = Template.bind({})
TrendsTableBreakdownInsight.args = {
    insight: trendsTableBreakdownInsight,
}

export const TrendsPieInsight: Story = Template.bind({})
TrendsPieInsight.args = { insight: trendsPieInsight }

export const TrendsPieInsightLegend: Story = Template.bind({})
TrendsPieInsightLegend.args = {
    insight: trendsPieInsight,
    legend: true,
}

export const TrendsPieInsightDetailed: Story = Template.bind({})
TrendsPieInsightDetailed.args = {
    insight: trendsPieInsight,
    detailed: true,
}

export const TrendsPieBreakdownInsight: Story = Template.bind({})
TrendsPieBreakdownInsight.args = {
    insight: trendsPieBreakdownInsight,
}

export const TrendsWorldMapInsight: Story = Template.bind({})
TrendsWorldMapInsight.args = {
    insight: trendsWorldMapInsight,
}
