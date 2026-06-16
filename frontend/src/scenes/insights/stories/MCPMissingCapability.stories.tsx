import { samplePersonProperties } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'

import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Scenes-App/Insights/MCP Missing Capability',
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            snapshotBrowsers: ['chromium'],
            viewport: {
                width: 1300,
                height: 720,
            },
        },
        viewMode: 'story',
        mockDate: '2026-06-07',
    },
    decorators: [
        mswDecorator({
            get: {
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
export const MCPMissingCapability: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/mcpMissingCapability.json')
)
MCPMissingCapability.parameters = {
    testOptions: { waitForSelector: '[data-attr=insights-table-graph] td' },
}
