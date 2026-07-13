import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

import __trendsSlopeGraph from '../../../mocks/fixtures/api/projects/team_id/insights/trendsSlopeGraph.json'

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
export const TrendsSlopeGraph: Story = createInsightStory(__trendsSlopeGraph as any)
TrendsSlopeGraph.parameters = { testOptions: { waitForSelector: '[data-attr=trends-slope-graph] canvas' } }
export const TrendsSlopeGraphEdit: Story = createInsightStory(__trendsSlopeGraph as any, 'edit')
TrendsSlopeGraphEdit.parameters = { testOptions: { waitForSelector: '[data-attr=trends-slope-graph] canvas' } }
// With the "Show legend" toggle on, the slope chart shows its own legend with each series'
// first-to-last change — there's only ever the one legend.
export const TrendsSlopeGraphWithLegend: Story = createInsightStory(__trendsSlopeGraph as any, 'view', true)
TrendsSlopeGraphWithLegend.parameters = { testOptions: { waitForSelector: '[data-attr=trends-slope-graph] canvas' } }
// The backend flags the last bucket as the current incomplete period (`incomplete_end`), so the
// second half of the connector to the end point is dashed — the same affordance the line chart uses.
const slopeInsight = __trendsSlopeGraph as any
export const TrendsSlopeGraphIncompletePeriod: Story = createInsightStory({
    ...slopeInsight,
    result: slopeInsight.result.map((series: Record<string, unknown>) => ({ ...series, incomplete_end: true })),
})
TrendsSlopeGraphIncompletePeriod.parameters = {
    testOptions: { waitForSelector: '[data-attr=trends-slope-graph] canvas' },
}
/* eslint-enable @typescript-eslint/no-var-requires */
