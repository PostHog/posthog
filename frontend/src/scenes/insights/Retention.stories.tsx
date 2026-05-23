import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'
import type { InsightVizNode, RetentionQuery } from '~/queries/schema/schema-general'
import type { QueryBasedInsightModel } from '~/types'
import { ChartDisplayType } from '~/types'

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Scenes-App/Insights/Retention',
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

// Retention

export const Retention: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/retention.json')
)
Retention.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}
export const RetentionEdit: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/retention.json'),
    'edit'
)
RetentionEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}

export const RetentionEditViewports: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/retention.json'),
    'edit'
)
RetentionEditViewports.parameters = {
    testOptions: {
        waitForSelector: '[data-attr=trend-line-graph] > canvas',
        viewportWidths: ['medium', 'wide', 'superwide'],
    },
}

const retentionInsight =
    require('../../mocks/fixtures/api/projects/team_id/insights/retention.json') as QueryBasedInsightModel
const retentionBaseQuery = retentionInsight.query as InsightVizNode
const retentionBaseSource = retentionBaseQuery.source as RetentionQuery
const retentionBarQuery: InsightVizNode = {
    ...retentionBaseQuery,
    source: {
        ...retentionBaseSource,
        retentionFilter: { ...retentionBaseSource.retentionFilter, display: ChartDisplayType.ActionsBar },
    },
}
const retentionBarInsight: QueryBasedInsightModel = { ...retentionInsight, query: retentionBarQuery }

export const RetentionBar: Story = createInsightStory(retentionBarInsight)
RetentionBar.parameters = {
    featureFlags: [FEATURE_FLAGS.PRODUCT_ANALYTICS_HOG_CHARTS_RETENTION_BAR],
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}

/* eslint-enable @typescript-eslint/no-var-requires */
