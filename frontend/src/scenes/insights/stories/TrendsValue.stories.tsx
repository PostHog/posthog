import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'

import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

import __trendsValue from '../../../mocks/fixtures/api/projects/team_id/insights/trendsValue.json'

// One representative edit-mode scene story for the trends editor — the editor is the same for
// every trends display type, and chart rendering itself is covered by the component-level
// stories in products/product_analytics/frontend/insights/trends/.
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

export const TrendsValueEdit: Story = createInsightStory(__trendsValue as any, 'edit')
TrendsValueEdit.parameters = {
    testOptions: { waitForSelector: '[data-attr=trend-bar-value-graph] > canvas' },
}

export const TrendsValueEditViewports: Story = createInsightStory(__trendsValue as any, 'edit')
TrendsValueEditViewports.parameters = {
    testOptions: {
        waitForSelector: '[data-attr=trend-bar-value-graph] > canvas',
        viewportWidths: ['medium', 'wide', 'superwide'],
    },
}

/* eslint-enable @typescript-eslint/no-var-requires */
