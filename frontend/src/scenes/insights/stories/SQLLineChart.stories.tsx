import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

type Story = StoryObj<typeof App>
const meta: Meta = {
    title: 'Scenes-App/Insights/SQLLineChart',
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
export const SQLLineChart: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/sqlLineChart.json')
)
SQLLineChart.parameters = {
    ...meta.parameters,
    testOptions: {
        ...meta.parameters?.testOptions,
        waitForSelector: '.DataVisualization canvas',
    },
}

export const SQLLineChartBreakdown: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/sqlLineChartBreakdown.json')
)
SQLLineChartBreakdown.parameters = {
    ...meta.parameters,
    testOptions: {
        ...meta.parameters?.testOptions,
        waitForSelector: '.DataVisualization canvas',
    },
}
/* eslint-enable @typescript-eslint/no-var-requires */
