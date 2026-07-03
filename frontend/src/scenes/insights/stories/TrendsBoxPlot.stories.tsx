import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'

import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

import __trendsBoxPlot from '../../../mocks/fixtures/api/projects/team_id/insights/trendsBoxPlot.json'

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Scenes-App/Insights/TrendsBoxPlot',
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
export const TrendsBoxPlot: Story = createInsightStory(__trendsBoxPlot as any)
TrendsBoxPlot.parameters = { testOptions: { waitForSelector: '[data-attr=box-plot-graph] > canvas' } }
export const TrendsBoxPlotEdit: Story = createInsightStory(__trendsBoxPlot as any, 'edit')
TrendsBoxPlotEdit.parameters = { testOptions: { waitForSelector: '[data-attr=box-plot-graph] > canvas' } }
/* eslint-enable @typescript-eslint/no-var-requires */
