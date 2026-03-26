import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

type Story = StoryObj<typeof App>
const meta: Meta = {
    title: 'Scenes-App/Insights/BoldNumber',
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

export const Default: Story = createInsightStory(
    require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsNumber.json')
)
Default.parameters = { testOptions: { waitForSelector: '.BoldNumber__value' } }

export const EmptyResult: Story = createInsightStory(
    require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsNumberEmpty.json')
)
EmptyResult.parameters = { testOptions: { waitForSelector: '[data-attr="insight-empty-state"]' } }

export const CompareNullPrevious: Story = createInsightStory(
    require('../../../../mocks/fixtures/api/projects/team_id/insights/trendsNumberCompareNullPrevious.json')
)
CompareNullPrevious.parameters = { testOptions: { waitForSelector: '.BoldNumber__value' } }
