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
        // After the fixture's last bucket (2022-03-15) so every bucket is complete and the
        // connectors render solid; the IncompletePeriod story moves "now" into the range.
        mockDate: '2022-04-01',
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
// With the "Show legend" toggle on, the slope renders into the insight's shared legend slot
// (SlopeGraphLegend) showing each series' first-to-last change — and no second in-chart legend.
export const TrendsSlopeGraphWithLegend: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsSlopeGraph.json'),
    'view',
    true
)
TrendsSlopeGraphWithLegend.parameters = { testOptions: { waitForSelector: '[data-attr=trends-slope-graph] canvas' } }
// "now" sits inside the fixture's range, so the last bucket is the current incomplete period and
// the connector to the end point is dashed — the same affordance the line chart uses.
export const TrendsSlopeGraphIncompletePeriod: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsSlopeGraph.json')
)
TrendsSlopeGraphIncompletePeriod.parameters = {
    mockDate: '2022-03-13',
    testOptions: { waitForSelector: '[data-attr=trends-slope-graph] canvas' },
}
/* eslint-enable @typescript-eslint/no-var-requires */
