import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'

import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

import __trendsWorldMap from '../../../mocks/fixtures/api/projects/team_id/insights/trendsWorldMap.json'

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Scenes-App/Insights/TrendsPie',
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

// Trends World Map (no hog-charts equivalent yet — keep these)
export const TrendsWorldMap: Story = createInsightStory(__trendsWorldMap as any)
TrendsWorldMap.parameters = { testOptions: { waitForSelector: '.WorldMap' } }
export const TrendsWorldMapEdit: Story = createInsightStory(__trendsWorldMap as any, 'edit')
TrendsWorldMapEdit.parameters = { testOptions: { waitForSelector: '.WorldMap' } }

/* eslint-enable @typescript-eslint/no-var-requires */
