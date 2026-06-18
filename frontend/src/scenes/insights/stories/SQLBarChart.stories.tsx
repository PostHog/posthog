import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

type Story = StoryObj<{}>

// Renders SQL bar charts through @posthog/quill-charts (TimeSeriesBarChart), gated behind the
// `product-analytics-quill-sql-charts` flag — these stories pin it on. The legacy chart.js path is
// covered when the flag is off.
const meta: Meta = {
    title: 'Scenes-App/Insights/SQLBarChart',
    parameters: {
        layout: 'fullscreen',
        featureFlags: [FEATURE_FLAGS.PRODUCT_ANALYTICS_QUILL_SQL_CHARTS],
        testOptions: {
            snapshotBrowsers: ['chromium'],
            viewport: {
                // needs a slightly larger width to push the rendered scene away from breakpoint boundary
                width: 1300,
                height: 720,
            },
        },
        viewMode: 'story',
        mockDate: '2022-03-11',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/persons/retention': sampleRetentionPeopleResponse,
                '/api/environments/:team_id/persons/properties': samplePersonProperties,
                '/api/projects/:team_id/groups_types': [],
            },
            post: {
                '/api/projects/:team_id/cohorts/': { id: 1 },
            },
        }),
    ],
}

export default meta

const waitForCanvas = {
    waitForSelector: '.DataVisualization canvas',
}

/* eslint-disable @typescript-eslint/no-var-requires */
export const SQLBarChartQuill: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/sqlBarChart.json')
)
SQLBarChartQuill.parameters = {
    ...meta.parameters,
    testOptions: { ...meta.parameters?.testOptions, ...waitForCanvas },
}

export const SQLStackedBarChartQuill: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/sqlStackedBarChart.json')
)
SQLStackedBarChartQuill.parameters = {
    ...meta.parameters,
    testOptions: { ...meta.parameters?.testOptions, ...waitForCanvas },
}

export const SQLPercentStackedBarChartQuill: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/sqlPercentStackedBarChart.json')
)
SQLPercentStackedBarChartQuill.parameters = {
    ...meta.parameters,
    testOptions: { ...meta.parameters?.testOptions, ...waitForCanvas },
}
/* eslint-enable @typescript-eslint/no-var-requires */
