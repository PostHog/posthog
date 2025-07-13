import { Meta, StoryObj } from '@storybook/react'
import { App } from 'scenes/App'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'
import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { mswDecorator } from '~/mocks/browser'

import funnelLeftToRightInsight from '../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json?url'
import funnelLeftToRightBreakdownInsight from '../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRightBreakdown.json?url'
import funnelHistoricalTrendsInsight from '../../mocks/fixtures/api/projects/team_id/insights/funnelHistoricalTrends.json?url'
import funnelTimeToConvertInsight from '../../mocks/fixtures/api/projects/team_id/insights/funnelTimeToConvert.json?url'

type Story = StoryObj<typeof App>
const meta: Meta = {
    title: 'Scenes-App/Insights/Funnels',
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

// Funnels
export const FunnelLeftToRight: Story = createInsightStory(funnelLeftToRightInsight)
FunnelLeftToRight.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-bar-vertical] .StepBar', '.PayGateMini'] },
}
export const FunnelLeftToRightEdit: Story = createInsightStory(funnelLeftToRightInsight, 'edit')
FunnelLeftToRightEdit.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-bar-vertical] .StepBar', '.PayGateMini'] },
}

export const FunnelLeftToRightBreakdown: Story = createInsightStory(funnelLeftToRightBreakdownInsight)
FunnelLeftToRightBreakdown.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-bar-vertical] .StepBar', '.PayGateMini'] },
}
export const FunnelLeftToRightBreakdownEdit: Story = createInsightStory(funnelLeftToRightBreakdownInsight, 'edit')
FunnelLeftToRightBreakdownEdit.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-bar-vertical] .StepBar', '.PayGateMini'] },
}

export const FunnelHistoricalTrends: Story = createInsightStory(funnelHistoricalTrendsInsight)
FunnelHistoricalTrends.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph-funnel] > canvas' },
}
export const FunnelHistoricalTrendsEdit: Story = createInsightStory(funnelHistoricalTrendsInsight, 'edit')
FunnelHistoricalTrendsEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph-funnel] > canvas' },
}

export const FunnelTimeToConvert: Story = createInsightStory(funnelTimeToConvertInsight)
FunnelTimeToConvert.parameters = { testOptions: { waitForSelector: '[data-attr=funnel-histogram] svg' } }
export const FunnelTimeToConvertEdit: Story = createInsightStory(funnelTimeToConvertInsight, 'edit')
FunnelTimeToConvertEdit.parameters = { testOptions: { waitForSelector: '[data-attr=funnel-histogram] svg' } }
