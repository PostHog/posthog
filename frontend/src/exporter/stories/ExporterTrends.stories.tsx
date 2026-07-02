import type { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { ExportType, ExportedData } from '~/exporter/types'

import __trendsArea from '../../mocks/fixtures/api/projects/team_id/insights/trendsArea.json'
import __trendsAreaBreakdown from '../../mocks/fixtures/api/projects/team_id/insights/trendsAreaBreakdown.json'
import __trendsBar from '../../mocks/fixtures/api/projects/team_id/insights/trendsBar.json'
import __trendsBarBreakdown from '../../mocks/fixtures/api/projects/team_id/insights/trendsBarBreakdown.json'
import __trendsLine from '../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'
import __trendsLineBreakdown from '../../mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdown.json'
import __trendsLineMulti from '../../mocks/fixtures/api/projects/team_id/insights/trendsLineMulti.json'
import __trendsNumber from '../../mocks/fixtures/api/projects/team_id/insights/trendsNumber.json'
import __trendsPie from '../../mocks/fixtures/api/projects/team_id/insights/trendsPie.json'
import __trendsPieBreakdown from '../../mocks/fixtures/api/projects/team_id/insights/trendsPieBreakdown.json'
import __trendsTable from '../../mocks/fixtures/api/projects/team_id/insights/trendsTable.json'
import __trendsTableBreakdown from '../../mocks/fixtures/api/projects/team_id/insights/trendsTableBreakdown.json'
import __trendsValue from '../../mocks/fixtures/api/projects/team_id/insights/trendsValue.json'
import __trendsValueBreakdown from '../../mocks/fixtures/api/projects/team_id/insights/trendsValueBreakdown.json'
import __trendsWorldMap from '../../mocks/fixtures/api/projects/team_id/insights/trendsWorldMap.json'
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
    args: { insight: __trendsLine as any },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsLineInsightLegend: Story = {
    args: {
        insight: __trendsLine as any,
        legend: true,
    },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsLineInsightDetailed: Story = {
    args: {
        insight: __trendsLine as any,
        detailed: true,
    },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

/** This should not happen in the exporter, but if it does, it shouldn't error out - we want a clear message. */
export const TrendsLineInsightNoResults: Story = {
    args: {
        insight: {
            ...(__trendsLine as any),
            result: null,
        },
    },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsLineMultiInsight: Story = {
    args: {
        insight: __trendsLineMulti as any,
    },
    parameters: {
        mockDate: '2023-07-10',
    },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsLineBreakdownInsight: Story = {
    args: {
        insight: __trendsLineBreakdown as any,
    },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsBarInsight: Story = {
    args: { insight: __trendsBar as any },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsBarBreakdownInsight: Story = {
    args: {
        insight: __trendsBarBreakdown as any,
    },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsValueInsight: Story = {
    args: { insight: __trendsValue as any },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsValueBreakdownInsight: Story = {
    args: {
        insight: __trendsValueBreakdown as any,
    },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsAreaInsight: Story = {
    args: { insight: __trendsArea as any },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsAreaBreakdownInsight: Story = {
    args: {
        insight: __trendsAreaBreakdown as any,
    },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsNumberInsight: Story = {
    args: { insight: __trendsNumber as any },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const TrendsTableInsight: Story = {
    args: { insight: __trendsTable as any },
}

export const TrendsTableBreakdownInsight: Story = {
    args: {
        insight: __trendsTableBreakdown as any,
    },
}

export const TrendsPieInsight: Story = {
    args: { insight: __trendsPie as any },
}

export const TrendsPieInsightLegend: Story = {
    args: {
        insight: __trendsPie as any,
        legend: true,
    },
}

export const TrendsPieInsightDetailed: Story = {
    args: {
        insight: __trendsPie as any,
        detailed: true,
    },
}

export const TrendsPieBreakdownInsight: Story = {
    args: {
        insight: __trendsPieBreakdown as any,
    },
}

export const TrendsWorldMapInsight: Story = {
    args: {
        insight: __trendsWorldMap as any,
    },
}
