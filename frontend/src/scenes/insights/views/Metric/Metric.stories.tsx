import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { InsightVizStory } from 'scenes/insights/__mocks__/createInsightVizStory'

import __trendsMetric from '~/mocks/fixtures/api/projects/team_id/insights/trendsMetric.json'

import { MetricCard } from './Metric'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/Metric',
    component: MetricCard,
    parameters: {
        layout: 'centered',
        mockDate: '2022-04-01',
        featureFlags: [FEATURE_FLAGS.METRIC_INSIGHT],
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
