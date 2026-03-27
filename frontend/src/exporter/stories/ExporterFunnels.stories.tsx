import type { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { ExportType, ExportedData } from '~/exporter/types'

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

export const FunnelLeftToRightInsight: Story = {
    args: {
        insight: require('../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json'),
    },
}

/** This should not happen in the exporter, but if it does, it shouldn't error out - we want a clear message. */
export const FunnelLeftToRightInsightNoResults: Story = {
    args: {
        insight: {
            ...require('../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json'),
            result: null,
        },
    },
}

export const FunnelLeftToRightBreakdownInsight: Story = {
    args: {
        insight: require('../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRightBreakdown.json'),
    },
}

export const FunnelTopToBottomInsight: Story = {
    args: {
        insight: require('../../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json'),
    },
}
/** This should not happen in the exporter, but if it does, it shouldn't error out - we want a clear message. */
export const FunnelTopToBottomInsightNoResults: Story = {
    args: {
        insight: {
            ...require('../../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottom.json'),
            result: null,
        },
    },
}

export const FunnelTopToBottomBreakdownInsight: Story = {
    args: {
        insight: require('../../mocks/fixtures/api/projects/team_id/insights/funnelTopToBottomBreakdown.json'),
    },
}

export const FunnelHistoricalTrendsInsight: Story = {
    tags: ['test-skip'],
    args: {
        insight: require('../../mocks/fixtures/api/projects/team_id/insights/funnelHistoricalTrends.json'),
    },
}

export const FunnelTimeToConvertInsight: Story = {
    args: {
        insight: require('../../mocks/fixtures/api/projects/team_id/insights/funnelTimeToConvert.json'),
    },
}
