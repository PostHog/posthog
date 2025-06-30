import { Meta, StoryObj } from '@storybook/react'
import { App } from 'scenes/App'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'
import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { mswDecorator } from '~/mocks/browser'

type Story = StoryObj<typeof App>
const meta: Meta = {
    title: 'Scenes-App/Insights/TrendsPie',
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
// Trends Pie
export const TrendsPie: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsPie.json')
)
TrendsPie.parameters = { testOptions: { waitForSelector: '[data-attr=trend-pie-graph] > canvas' } }
export const TrendsPieEdit: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsPie.json'),
    'edit'
)
TrendsPieEdit.parameters = { testOptions: { waitForSelector: '[data-attr=trend-pie-graph] > canvas' } }

export const TrendsPieBreakdown: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsPieBreakdown.json')
)
TrendsPieBreakdown.parameters = { testOptions: { waitForSelector: '[data-attr=trend-pie-graph] > canvas' } }
export const TrendsPieBreakdownEdit: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsPieBreakdown.json'),
    'edit'
)
TrendsPieBreakdownEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-pie-graph] > canvas' },
}

export const TrendsPieBreakdownLabels: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsPieBreakdown.json'),
    'view',
    true
)
TrendsPieBreakdownLabels.parameters = { testOptions: { waitForSelector: '[data-attr=trend-pie-graph] > canvas' } }

// Trends World Map
export const TrendsWorldMap: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsWorldMap.json')
)
TrendsWorldMap.parameters = { testOptions: { waitForSelector: '.WorldMap' } }
export const TrendsWorldMapEdit: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsWorldMap.json'),
    'edit'
)
TrendsWorldMapEdit.parameters = { testOptions: { waitForSelector: '.WorldMap' } }
/* eslint-enable @typescript-eslint/no-var-requires */
