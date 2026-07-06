import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'

import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

import __dataTableHogQL from '../../../mocks/fixtures/api/projects/team_id/insights/dataTableHogQL.json'
import __dataVisualizationHogQL from '../../../mocks/fixtures/api/projects/team_id/insights/dataVisualizationHogQL.json'
import __trendsLine from '../../../mocks/fixtures/api/projects/team_id/insights/trendsLine.json'

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

export const SavedTrendsInsight: Story = createInsightStory(__trendsLine as any, 'view', false, { openSidePanel: true })

export const SavedHogQLDataTable: Story = createInsightStory(__dataTableHogQL as any, 'view', false, {
    openSidePanel: true,
})

export const SavedDataVisualization: Story = createInsightStory(__dataVisualizationHogQL as any, 'view', false, {
    openSidePanel: true,
})

const unsavedInsight = {
    ...(__trendsLine as any),
    id: undefined,
    short_id: undefined,
    saved: false,
}
export const UnsavedInsight: Story = createInsightStory(unsavedInsight, 'edit', false, { openSidePanel: true })
