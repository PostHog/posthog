import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'

import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

import __trendsArea from '../../../mocks/fixtures/api/projects/team_id/insights/trendsArea.json'
import __trendsAreaBreakdown from '../../../mocks/fixtures/api/projects/team_id/insights/trendsAreaBreakdown.json'
import __trendsNumber from '../../../mocks/fixtures/api/projects/team_id/insights/trendsNumber.json'
import __trendsTable from '../../../mocks/fixtures/api/projects/team_id/insights/trendsTable.json'
import __trendsTableBreakdown from '../../../mocks/fixtures/api/projects/team_id/insights/trendsTableBreakdown.json'
import __trendsValue from '../../../mocks/fixtures/api/projects/team_id/insights/trendsValue.json'
import __trendsValueBreakdown from '../../../mocks/fixtures/api/projects/team_id/insights/trendsValueBreakdown.json'

type Story = StoryObj<{}>
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
export const TrendsValue: Story = createInsightStory(__trendsValue as any)
TrendsValue.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-bar-value-graph] > canvas' },
}
export const TrendsValueEdit: Story = createInsightStory(__trendsValue as any, 'edit')
TrendsValueEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-bar-value-graph] > canvas' },
}

export const TrendsValueBreakdown: Story = createInsightStory(__trendsValueBreakdown as any)
TrendsValueBreakdown.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-bar-value-graph] > canvas' },
}
export const TrendsValueBreakdownEdit: Story = createInsightStory(__trendsValueBreakdown as any, 'edit')
TrendsValueBreakdownEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-bar-value-graph] > canvas' },
}

// Trends Area
export const TrendsArea: Story = createInsightStory(__trendsArea as any)
TrendsArea.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsAreaEdit: Story = createInsightStory(__trendsArea as any, 'edit')
TrendsAreaEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsAreaBreakdown: Story = createInsightStory(__trendsAreaBreakdown as any)
TrendsAreaBreakdown.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsAreaBreakdownEdit: Story = createInsightStory(__trendsAreaBreakdown as any, 'edit')
TrendsAreaBreakdownEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}

// Trends Number
export const TrendsNumber: Story = createInsightStory(__trendsNumber as any)
TrendsNumber.parameters = { testOptions: { waitForSelector: '.BoldNumber__value' } }
export const TrendsNumberEdit: Story = createInsightStory(__trendsNumber as any, 'edit')
TrendsNumberEdit.parameters = { testOptions: { waitForSelector: '.BoldNumber__value' } }

// Trends Table
export const TrendsTable: Story = createInsightStory(__trendsTable as any)
TrendsTable.parameters = { testOptions: { waitForSelector: '[data-attr=insights-table-graph] td' } }
export const TrendsTableEdit: Story = createInsightStory(__trendsTable as any, 'edit')
TrendsTableEdit.parameters = { testOptions: { waitForSelector: '[data-attr=insights-table-graph] td' } }

export const TrendsTableBreakdown: Story = createInsightStory(__trendsTableBreakdown as any)
TrendsTableBreakdown.parameters = { testOptions: { waitForSelector: '[data-attr=insights-table-graph] td' } }
export const TrendsTableBreakdownEdit: Story = createInsightStory(__trendsTableBreakdown as any, 'edit')
TrendsTableBreakdownEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=insights-table-graph] td' },
}
export const TrendsValueEditViewports: Story = createInsightStory(__trendsValue as any, 'edit')
TrendsValueEditViewports.parameters = {
    testOptions: {
        waitForSelector: '[data-attr=trend-bar-value-graph] > canvas',
        viewportWidths: ['medium', 'wide', 'superwide'],
    },
}

/* eslint-enable @typescript-eslint/no-var-requires */
