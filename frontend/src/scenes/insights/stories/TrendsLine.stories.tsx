import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'

import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

import __trendsLineBreakdown from '../../../mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdown.json'

// One edit-mode scene story with a breakdown applied. This is the only snapshot of the insight
// editor's populated "Breakdown by" section, and the only place a time-series trends result flows
// through the full scene pipeline (routing → insight fetch → query POST → dataNodeLogic) — the
// aggregated-result path is covered by TrendsValue.stories.tsx, and chart rendering itself by the
// component-level stories in products/product_analytics/frontend/insights/trends/.
type Story = StoryObj<{}>
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

export const TrendsLineBreakdownEdit: Story = createInsightStory(__trendsLineBreakdown as any, 'edit')
TrendsLineBreakdownEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-line-graph] > canvas' },
}

/* eslint-enable @typescript-eslint/no-var-requires */
