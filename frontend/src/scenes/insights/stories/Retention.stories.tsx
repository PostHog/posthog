import { FEATURE_FLAGS } from 'lib/constants'
import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'

import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Scenes-App/Insights/Retention',
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            snapshotBrowsers: ['chromium'],
            viewport: {
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
const retentionFixture = require('../../../mocks/fixtures/api/projects/team_id/insights/retention.json')

// Retention rendered as an area chart on the new quill-charts path
// (PRODUCT_ANALYTICS_HOG_CHARTS_RETENTION). `display: ActionsAreaGraph` flows through
// `buildRetentionSeries` as `fill: {}` per cohort, which the chart auto-stacks.
const retentionArea = {
    ...retentionFixture,
    query: {
        ...retentionFixture.query,
        source: {
            ...retentionFixture.query.source,
            retentionFilter: {
                ...retentionFixture.query.source.retentionFilter,
                display: 'ActionsAreaGraph',
            },
        },
    },
}

export const RetentionAreaGraphHogCharts: Story = createInsightStory(retentionArea)
RetentionAreaGraphHogCharts.parameters = {
    featureFlags: [FEATURE_FLAGS.PRODUCT_ANALYTICS_HOG_CHARTS_RETENTION],
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] canvas' },
}
/* eslint-enable @typescript-eslint/no-var-requires */
