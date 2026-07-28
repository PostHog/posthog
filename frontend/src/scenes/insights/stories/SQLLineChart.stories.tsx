import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

import __sqlBarChartValueLabels from '../../../mocks/fixtures/api/projects/team_id/insights/sqlBarChartValueLabels.json'
import __sqlLineChart from '../../../mocks/fixtures/api/projects/team_id/insights/sqlLineChart.json'
import __sqlLineChartBreakdown from '../../../mocks/fixtures/api/projects/team_id/insights/sqlLineChartBreakdown.json'
import __sqlLineChartTrendLine from '../../../mocks/fixtures/api/projects/team_id/insights/sqlLineChartTrendLine.json'

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Scenes-App/Insights/SQLLineChart',
    parameters: {
        layout: 'fullscreen',
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

/* eslint-disable @typescript-eslint/no-var-requires */
export const SQLLineChart: Story = createInsightStory(__sqlLineChart as any)
SQLLineChart.parameters = {
    ...meta.parameters,
    testOptions: {
        ...meta.parameters?.testOptions,
        waitForSelector: '.DataVisualization canvas',
    },
}

export const SQLLineChartBreakdown: Story = createInsightStory(__sqlLineChartBreakdown as any)
SQLLineChartBreakdown.parameters = {
    ...meta.parameters,
    testOptions: {
        ...meta.parameters?.testOptions,
        waitForSelector: '.DataVisualization canvas',
    },
}

export const SQLLineChartTrendLineQuill: Story = createInsightStory(__sqlLineChartTrendLine as any)
SQLLineChartTrendLineQuill.parameters = {
    ...meta.parameters,
    featureFlags: [FEATURE_FLAGS.PRODUCT_ANALYTICS_QUILL_SQL_CHARTS],
    testOptions: {
        ...meta.parameters?.testOptions,
        waitForSelector: '.DataVisualization canvas',
    },
}

// The legacy chart.js SQL renderer does not paint in the visual-regression harness (a pre-existing gap
// that also affects the SQL line stories above), so this story targets the quill renderer, which does.
export const SQLBarChartValueLabelsQuill: Story = createInsightStory(__sqlBarChartValueLabels as any)
SQLBarChartValueLabelsQuill.parameters = {
    ...meta.parameters,
    featureFlags: [FEATURE_FLAGS.PRODUCT_ANALYTICS_QUILL_SQL_CHARTS],
    testOptions: {
        ...meta.parameters?.testOptions,
        waitForSelector: '.DataVisualization canvas',
    },
}
/* eslint-enable @typescript-eslint/no-var-requires */
