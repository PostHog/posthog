import type { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { ExportType, ExportedData } from '~/exporter/types'

import { Exporter } from '../Exporter'

type Story = StoryObj<ExportedData>
const meta: Meta<ExportedData> = {
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
    render: (props) => {
        useEffect(() => {
            document.body.className = ''
            document.documentElement.className = `export-type-${props.type}`
        }, [props.type])
        return (
            <div className={`storybook-export-type-${props.type} p-4`}>
                <Exporter {...props} />
            </div>
        )
    },
}

export default meta

export const TrendsLineInsight: Story = {
    args: { insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json') },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsLineInsightLegend: Story = {
    args: {
        insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'),
        legend: true,
    },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsLineInsightDetailed: Story = {
    args: {
        insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'),
        detailed: true,
    },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

/** This should not happen in the exporter, but if it does, it shouldn't error out - we want a clear message. */
export const TrendsLineInsightNoResults: Story = {
    args: {
        insight: {
            ...require('../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'),
            result: null,
        },
    },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsLineMultiInsight: Story = {
    args: {
        insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsLineMulti.json'),
    },
    parameters: {
        mockDate: '2023-07-10',
    },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsLineBreakdownInsight: Story = {
    args: {
        insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdown.json'),
    },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsBarInsight: Story = {
    args: { insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsBar.json') },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsBarBreakdownInsight: Story = {
    args: {
        insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsBarBreakdown.json'),
    },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsValueInsight: Story = {
    args: { insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsValue.json') },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsValueBreakdownInsight: Story = {
    args: {
        insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsValueBreakdown.json'),
    },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsAreaInsight: Story = {
    args: { insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsArea.json') },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsAreaBreakdownInsight: Story = {
    args: {
        insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsAreaBreakdown.json'),
    },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsNumberInsight: Story = {
    args: { insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsNumber.json') },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsTableInsight: Story = {
    args: { insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsTable.json') },
}

export const TrendsTableBreakdownInsight: Story = {
    args: {
        insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsTableBreakdown.json'),
    },
}

export const TrendsPieInsight: Story = {
    args: { insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsPie.json') },
}

export const TrendsPieInsightLegend: Story = {
    args: {
        insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsPie.json'),
        legend: true,
    },
}

export const TrendsPieInsightDetailed: Story = {
    args: {
        insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsPie.json'),
        detailed: true,
    },
}

export const TrendsPieBreakdownInsight: Story = {
    args: {
        insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsPieBreakdown.json'),
    },
}

export const TrendsWorldMapInsight: Story = {
    args: {
        insight: require('../../mocks/fixtures/api/projects/team_id/insights/trendsWorldMap.json'),
    },
}
