import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Scenes-App/Insights/TrendsSlopeGraph',
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
        featureFlags: [FEATURE_FLAGS.SLOPE_GRAPH_INSIGHT],
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
export const TrendsSlopeGraph: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsSlopeGraph.json')
)
TrendsSlopeGraph.parameters = { testOptions: { waitForSelector: '[data-attr=trends-slope-graph] canvas' } }
export const TrendsSlopeGraphEdit: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsSlopeGraph.json'),
    'edit'
)
TrendsSlopeGraphEdit.parameters = { testOptions: { waitForSelector: '[data-attr=trends-slope-graph] canvas' } }
/* eslint-enable @typescript-eslint/no-var-requires */
