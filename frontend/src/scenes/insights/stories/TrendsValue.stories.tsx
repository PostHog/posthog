import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

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
/* eslint-disable @typescript-eslint/no-var-requires */
// Trends Value
export const TrendsValue: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsValue.json')
)
TrendsValue.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-bar-value-graph] > canvas' },
}
export const TrendsValueEdit: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsValue.json'),
    'edit'
)
TrendsValueEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-bar-value-graph] > canvas' },
}

export const TrendsValueBreakdown: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsValueBreakdown.json')
)
TrendsValueBreakdown.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-bar-value-graph] > canvas' },
}
export const TrendsValueBreakdownEdit: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsValueBreakdown.json'),
    'edit'
)
TrendsValueBreakdownEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-bar-value-graph] > canvas' },
}

// Trends Area
export const TrendsArea: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsArea.json')
)
TrendsArea.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsAreaEdit: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsArea.json'),
    'edit'
)
TrendsAreaEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsAreaBreakdown: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsAreaBreakdown.json')
)
TrendsAreaBreakdown.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsAreaBreakdownEdit: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsAreaBreakdown.json'),
    'edit'
)
TrendsAreaBreakdownEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}

// Trends Number
export const TrendsNumber: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsNumber.json')
)
TrendsNumber.parameters = { testOptions: { waitForSelector: '.BoldNumber__value' } }
export const TrendsNumberEdit: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsNumber.json'),
    'edit'
)
TrendsNumberEdit.parameters = { testOptions: { waitForSelector: '.BoldNumber__value' } }

// Trends Table
export const TrendsTable: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsTable.json')
)
TrendsTable.parameters = { testOptions: { waitForSelector: '[data-attr=insights-table-graph] td' } }
export const TrendsTableEdit: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsTable.json'),
    'edit'
)
TrendsTableEdit.parameters = { testOptions: { waitForSelector: '[data-attr=insights-table-graph] td' } }

export const TrendsTableBreakdown: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsTableBreakdown.json')
)
TrendsTableBreakdown.parameters = { testOptions: { waitForSelector: '[data-attr=insights-table-graph] td' } }
export const TrendsTableBreakdownEdit: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsTableBreakdown.json'),
    'edit'
)
TrendsTableBreakdownEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=insights-table-graph] td' },
}
/* eslint-enable @typescript-eslint/no-var-requires */
