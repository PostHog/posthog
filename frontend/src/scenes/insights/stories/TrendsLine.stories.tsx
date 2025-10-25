import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

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
/* eslint-disable @typescript-eslint/no-var-requires */
// Trends Line
export const TrendsLine: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json')
)
TrendsLine.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}

// FLAP!
// export const TrendsLineEdit: Story = createInsightStory(
//     require('../../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'),
//     'edit'
// )
// TrendsLineEdit.parameters = {
//     testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
// }

export const TrendsLineMulti: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsLineMulti.json')
)
TrendsLineMulti.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsLineMultiEdit: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsLineMulti.json'),
    'edit'
)
TrendsLineMultiEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsLineBreakdown: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdown.json')
)
TrendsLineBreakdown.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsLineBreakdownEdit: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdown.json'),
    'edit'
)
TrendsLineBreakdownEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsLineBreakdownLabels: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdown.json'),
    'view',
    true
)
TrendsLineBreakdownLabels.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}

// Trends Bar
export const TrendsBar: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsBar.json')
)
TrendsBar.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsBarEdit: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsBar.json'),
    'edit'
)
TrendsBarEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}

export const TrendsBarBreakdown: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsBarBreakdown.json')
)
TrendsBarBreakdown.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}
export const TrendsBarBreakdownEdit: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsBarBreakdown.json'),
    'edit'
)
TrendsBarBreakdownEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}
/* eslint-enable @typescript-eslint/no-var-requires */
