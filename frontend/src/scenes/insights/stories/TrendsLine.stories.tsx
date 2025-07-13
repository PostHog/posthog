import { Meta, StoryObj } from '@storybook/react'
import { App } from 'scenes/App'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'
import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { mswDecorator } from '~/mocks/browser'

import trendsLineInsight from '../../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json?url'
import trendsLineMultiInsight from '../../../mocks/fixtures/api/projects/team_id/insights/trendsLineMulti.json?url'
import trendsLineBreakdownInsight from '../../../mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdown.json?url'
import trendsBarInsight from '../../../mocks/fixtures/api/projects/team_id/insights/trendsBar.json?url'
import trendsBarBreakdownInsight from '../../../mocks/fixtures/api/projects/team_id/insights/trendsBarBreakdown.json?url'

type Story = StoryObj<typeof App>
const meta: Meta = {
    title: 'Scenes-App/Insights/TrendsLine',
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

// Trends Line
export const TrendsLine: Story = createInsightStory(trendsLineInsight)
TrendsLine.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsLineEdit: Story = createInsightStory(trendsLineInsight, 'edit')
TrendsLineEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsLineMulti: Story = createInsightStory(trendsLineMultiInsight)
TrendsLineMulti.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsLineMultiEdit: Story = createInsightStory(trendsLineMultiInsight, 'edit')
TrendsLineMultiEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsLineBreakdown: Story = createInsightStory(trendsLineBreakdownInsight)
TrendsLineBreakdown.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsLineBreakdownEdit: Story = createInsightStory(trendsLineBreakdownInsight, 'edit')
TrendsLineBreakdownEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsLineBreakdownLabels: Story = createInsightStory(trendsLineBreakdownInsight, 'view', true)
TrendsLineBreakdownLabels.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}

// Trends Bar
export const TrendsBar: Story = createInsightStory(trendsBarInsight)
TrendsBar.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsBarEdit: Story = createInsightStory(trendsBarInsight, 'edit')
TrendsBarEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsBarBreakdown: Story = createInsightStory(trendsBarBreakdownInsight)
TrendsBarBreakdown.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsBarBreakdownEdit: Story = createInsightStory(trendsBarBreakdownInsight, 'edit')
TrendsBarBreakdownEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}
