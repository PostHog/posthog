import { Meta, StoryObj } from '@storybook/react'
import { App } from 'scenes/App'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'
import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { mswDecorator } from '~/mocks/browser'

import trendsValueInsight from '../../../mocks/fixtures/api/projects/team_id/insights/trendsValue.json?url'
import trendsValueBreakdownInsight from '../../../mocks/fixtures/api/projects/team_id/insights/trendsValueBreakdown.json?url'
import trendsAreaInsight from '../../../mocks/fixtures/api/projects/team_id/insights/trendsArea.json?url'
import trendsAreaBreakdownInsight from '../../../mocks/fixtures/api/projects/team_id/insights/trendsAreaBreakdown.json?url'
import trendsNumberInsight from '../../../mocks/fixtures/api/projects/team_id/insights/trendsNumber.json?url'
import trendsTableInsight from '../../../mocks/fixtures/api/projects/team_id/insights/trendsTable.json?url'
import trendsTableBreakdownInsight from '../../../mocks/fixtures/api/projects/team_id/insights/trendsTableBreakdown.json?url'

type Story = StoryObj<typeof App>
const meta: Meta = {
    title: 'Scenes-App/Insights/TrendsValue',
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

// Trends Value
export const TrendsValue: Story = createInsightStory(trendsValueInsight)
TrendsValue.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-bar-value-graph] > canvas' },
}
export const TrendsValueEdit: Story = createInsightStory(trendsValueInsight, 'edit')
TrendsValueEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-bar-value-graph] > canvas' },
}

export const TrendsValueBreakdown: Story = createInsightStory(trendsValueBreakdownInsight)
TrendsValueBreakdown.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-bar-value-graph] > canvas' },
}
export const TrendsValueBreakdownEdit: Story = createInsightStory(trendsValueBreakdownInsight, 'edit')
TrendsValueBreakdownEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-bar-value-graph] > canvas' },
}

// Trends Area
export const TrendsArea: Story = createInsightStory(trendsAreaInsight)
TrendsArea.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsAreaEdit: Story = createInsightStory(trendsAreaInsight, 'edit')
TrendsAreaEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsAreaBreakdown: Story = createInsightStory(trendsAreaBreakdownInsight)
TrendsAreaBreakdown.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsAreaBreakdownEdit: Story = createInsightStory(trendsAreaBreakdownInsight, 'edit')
TrendsAreaBreakdownEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}

// Trends Number
export const TrendsNumber: Story = createInsightStory(trendsNumberInsight)
TrendsNumber.parameters = { testOptions: { waitForSelector: '.BoldNumber__value' } }
export const TrendsNumberEdit: Story = createInsightStory(trendsNumberInsight, 'edit')
TrendsNumberEdit.parameters = { testOptions: { waitForSelector: '.BoldNumber__value' } }

// Trends Table
export const TrendsTable: Story = createInsightStory(trendsTableInsight)
TrendsTable.parameters = { testOptions: { waitForSelector: '[data-attr=insights-table-graph] td' } }
export const TrendsTableEdit: Story = createInsightStory(trendsTableInsight, 'edit')
TrendsTableEdit.parameters = { testOptions: { waitForSelector: '[data-attr=insights-table-graph] td' } }

export const TrendsTableBreakdown: Story = createInsightStory(trendsTableBreakdownInsight)
TrendsTableBreakdown.parameters = { testOptions: { waitForSelector: '[data-attr=insights-table-graph] td' } }
export const TrendsTableBreakdownEdit: Story = createInsightStory(trendsTableBreakdownInsight, 'edit')
TrendsTableBreakdownEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=insights-table-graph] td' },
}
