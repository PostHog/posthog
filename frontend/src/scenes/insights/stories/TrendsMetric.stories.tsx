import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

import __trendsMetric from '../../../mocks/fixtures/api/projects/team_id/insights/trendsMetric.json'

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Scenes-App/Insights/TrendsMetric',
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
        mockDate: '2022-04-01',
        featureFlags: [FEATURE_FLAGS.METRIC_INSIGHT],
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
export const TrendsMetric: Story = createInsightStory(__trendsMetric as any)
TrendsMetric.parameters = { testOptions: { waitForSelector: '.Metric canvas' } }
export const TrendsMetricEdit: Story = createInsightStory(__trendsMetric as any, 'edit')
TrendsMetricEdit.parameters = { testOptions: { waitForSelector: '.Metric canvas' } }
/* eslint-enable @typescript-eslint/no-var-requires */
