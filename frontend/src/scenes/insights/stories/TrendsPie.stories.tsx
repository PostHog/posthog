import { Meta, StoryObj } from '@storybook/react'
import { App } from 'scenes/App'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'
import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { mswDecorator } from '~/mocks/browser'
import { QueryBasedInsightModel } from '~/types'

import trendsPieInsightData from '../../../mocks/fixtures/api/projects/team_id/insights/trendsPie.json'
import trendsPieBreakdownInsightData from '../../../mocks/fixtures/api/projects/team_id/insights/trendsPieBreakdown.json'
import trendsWorldMapInsightData from '../../../mocks/fixtures/api/projects/team_id/insights/trendsWorldMap.json'

// Type assertions for JSON fixtures
const trendsPieInsight = trendsPieInsightData as unknown as QueryBasedInsightModel
const trendsPieBreakdownInsight = trendsPieBreakdownInsightData as unknown as QueryBasedInsightModel
const trendsWorldMapInsight = trendsWorldMapInsightData as unknown as QueryBasedInsightModel

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

// Trends Pie
export const TrendsPie: Story = createInsightStory(trendsPieInsight)
TrendsPie.parameters = { testOptions: { waitForSelector: '[data-attr=trend-pie-graph] > canvas' } }
export const TrendsPieEdit: Story = createInsightStory(trendsPieInsight, 'edit')
TrendsPieEdit.parameters = { testOptions: { waitForSelector: '[data-attr=trend-pie-graph] > canvas' } }

export const TrendsPieBreakdown: Story = createInsightStory(trendsPieBreakdownInsight)
TrendsPieBreakdown.parameters = { testOptions: { waitForSelector: '[data-attr=trend-pie-graph] > canvas' } }
export const TrendsPieBreakdownEdit: Story = createInsightStory(trendsPieBreakdownInsight, 'edit')
TrendsPieBreakdownEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-pie-graph] > canvas' },
}

export const TrendsPieBreakdownLabels: Story = createInsightStory(trendsPieBreakdownInsight, 'view', true)
TrendsPieBreakdownLabels.parameters = { testOptions: { waitForSelector: '[data-attr=trend-pie-graph] > canvas' } }

// Trends World Map
export const TrendsWorldMap: Story = createInsightStory(trendsWorldMapInsight)
TrendsWorldMap.parameters = { testOptions: { waitForSelector: '.WorldMap' } }
export const TrendsWorldMapEdit: Story = createInsightStory(trendsWorldMapInsight, 'edit')
TrendsWorldMapEdit.parameters = { testOptions: { waitForSelector: '.WorldMap' } }
