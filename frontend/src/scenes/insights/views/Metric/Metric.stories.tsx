import { Meta, StoryObj } from '@storybook/react'

import { InsightVizStory } from 'scenes/insights/__mocks__/createInsightVizStory'

import __trendsMetric from '~/mocks/fixtures/api/projects/team_id/insights/trendsMetric.json'

import { Metric } from './Metric'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/Metric',
    component: Metric,
    parameters: {
        layout: 'centered',
        mockDate: '2022-04-01',
        testOptions: {
            snapshotBrowsers: ['chromium'],
            waitForSelector: '.Metric canvas',
        },
    },
}
export default meta

export const Default: Story = {
    render: () => <InsightVizStory insight={__trendsMetric as any} />,
}
