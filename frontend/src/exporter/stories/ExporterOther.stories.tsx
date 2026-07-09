import type { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { ExportType, ExportedData } from '~/exporter/types'

import __dataTableEvents from '../../mocks/fixtures/api/projects/team_id/insights/dataTableEvents.json'
import __dataTableHogQL from '../../mocks/fixtures/api/projects/team_id/insights/dataTableHogQL.json'
import __lifecycle from '../../mocks/fixtures/api/projects/team_id/insights/lifecycle.json'
import __retention from '../../mocks/fixtures/api/projects/team_id/insights/retention.json'
import __stickiness from '../../mocks/fixtures/api/projects/team_id/insights/stickiness.json'
import __userPaths from '../../mocks/fixtures/api/projects/team_id/insights/userPaths.json'
import { Exporter } from '../Exporter'

type Story = StoryObj<ExportedData>
const meta: Meta<ExportedData> = {
    title: 'Exporter/Other',
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

export const RetentionInsight: Story = {
    args: { insight: __retention as any },
}

export const LifecycleInsight: Story = {
    args: { insight: __lifecycle as any },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const StickinessInsight: Story = {
    args: { insight: __stickiness as any },
    tags: ['test-skip'], // doesn't produce a helpful reference image, as canvas can't be captured
}

export const UserPathsInsight: Story = {
    args: { insight: __userPaths as any },
    tags: ['test-skip'], // FIXME: flaky tests, most likely due to resize observer changes
}

export const EventTableInsight: Story = {
    args: { insight: __dataTableEvents as any },
}

/** This should not happen in the exporter, but if it does, it shouldn't error out - we want a clear message. */
export const EventTableInsightNoResults: Story = {
    args: {
        insight: {
            ...(__dataTableEvents as any),
            result: null,
        },
    },
}

export const SQLInsight: Story = {
    args: { insight: __dataTableHogQL as any },
}

/** This should not happen in the exporter, but if it does, it shouldn't error out - we want a clear message. */
export const SQLInsightNoResults: Story = {
    args: {
        insight: {
            ...(__dataTableHogQL as any),
            result: null,
        },
    },
}
