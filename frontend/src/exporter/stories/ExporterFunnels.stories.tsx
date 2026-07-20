import type { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { ExportType, ExportedData } from '~/exporter/types'

import __funnelHistoricalTrends from '../../mocks/fixtures/api/projects/team_id/insights/funnelHistoricalTrends.json'
import __funnelTimeToConvert from '../../mocks/fixtures/api/projects/team_id/insights/funnelTimeToConvert.json'
import __funnelTopToBottom from '../../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json'
import { Exporter } from '../Exporter'

type Story = StoryObj<ExportedData>
const meta: Meta<ExportedData> = {
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

export const FunnelTopToBottomInsight: Story = {
    args: {
        insight: __funnelTopToBottom as any,
    },
}
/** This should not happen in the exporter, but if it does, it shouldn't error out - we want a clear message. */
export const FunnelTopToBottomInsightNoResults: Story = {
    args: {
        insight: {
            ...(__funnelTopToBottom as any),
            result: null,
        },
    },
}

export const FunnelHistoricalTrendsInsight: Story = {
    tags: ['test-skip'],
    args: {
        insight: __funnelHistoricalTrends as any,
    },
}

export const FunnelTimeToConvertInsight: Story = {
    args: {
        insight: __funnelTimeToConvert as any,
    },
}
