import { Meta, StoryObj } from '@storybook/react'
import { App } from 'scenes/App'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'
import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { mswDecorator } from '~/mocks/browser'

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
/* eslint-disable @typescript-eslint/no-var-requires */

// Funnels

export const FunnelLeftToRight: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json')
)
FunnelLeftToRight.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-bar-vertical] .StepBar', '.PayGateMini'] },
}
export const FunnelLeftToRightEdit: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRight.json'),
    'edit'
)
FunnelLeftToRightEdit.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-bar-vertical] .StepBar', '.PayGateMini'] },
}

export const FunnelLeftToRightBreakdown: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRightBreakdown.json')
)
FunnelLeftToRightBreakdown.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-bar-vertical] .StepBar', '.PayGateMini'] },
}
export const FunnelLeftToRightBreakdownEdit: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/funnelLeftToRightBreakdown.json'),
    'edit'
)
FunnelLeftToRightBreakdownEdit.parameters = {
    testOptions: { waitForSelector: ['[data-attr=funnel-bar-vertical] .StepBar', '.PayGateMini'] },
}

export const FunnelHistoricalTrends: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/funnelHistoricalTrends.json')
)
FunnelHistoricalTrends.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph-funnel] > canvas' },
}
export const FunnelHistoricalTrendsEdit: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/funnelHistoricalTrends.json'),
    'edit'
)
FunnelHistoricalTrendsEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph-funnel] > canvas' },
}

export const FunnelTimeToConvert: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/funnelTimeToConvert.json')
)
FunnelTimeToConvert.parameters = { testOptions: { waitForSelector: '[data-attr=funnel-histogram] svg' } }
export const FunnelTimeToConvertEdit: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/funnelTimeToConvert.json'),
    'edit'
)
FunnelTimeToConvertEdit.parameters = { testOptions: { waitForSelector: '[data-attr=funnel-histogram] svg' } }

/* eslint-enable @typescript-eslint/no-var-requires */
