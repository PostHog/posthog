import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'

import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Scenes-App/Insights/Side Panel Actions',
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            snapshotBrowsers: ['chromium'],
            viewport: { width: 1300, height: 900 },
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

export const SavedTrendsInsight: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'),
    'view',
    false,
    { openSidePanel: true }
)

export const SavedHogQLDataTable: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/dataTableHogQL.json'),
    'view',
    false,
    { openSidePanel: true }
)

export const SavedDataVisualization: Story = createInsightStory(
    require('../../../mocks/fixtures/api/projects/team_id/insights/dataVisualizationHogQL.json'),
    'view',
    false,
    { openSidePanel: true }
)

const unsavedInsight = {
    ...require('../../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'),
    id: undefined,
    short_id: undefined,
    saved: false,
}
export const UnsavedInsight: Story = createInsightStory(unsavedInsight, 'edit', false, { openSidePanel: true })
