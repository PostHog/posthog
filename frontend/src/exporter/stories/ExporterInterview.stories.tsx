import type { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { ExportType, ExportedData, InterviewExportPayload } from '~/exporter/types'

import { Exporter } from '../Exporter'

const interview: InterviewExportPayload = {
    topic_id: 'topic-123',
    interviewee_identifier: 'interviewee-abc',
    user_name: 'Sam',
    topic: 'how you use dashboards',
    already_replied: false,
}

type Story = StoryObj<ExportedData>
const meta: Meta<ExportedData> = {
    title: 'Exporter/Interview',
    component: Exporter,
    args: {
        type: ExportType.Interview,
        whitelabel: false,
        noHeader: false,
        legend: false,
        detailed: false,
        accessToken: 'storybook-access-token',
        interview,
    },
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            snapshotBrowsers: ['chromium'],
            viewportWidths: ['narrow', 'medium', 'wide', 'superwide'],
        },
        mockDate: '2023-02-01',
        viewMode: 'story',
    },
    tags: [],
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

export const Default: Story = {}
