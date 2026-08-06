import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

import __trendsLineMulti from '../../../mocks/fixtures/api/projects/team_id/insights/trendsLineMulti.json'
import __trendsNumber from '../../../mocks/fixtures/api/projects/team_id/insights/trendsNumber.json'

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Components/ChartDisplaySuggestions',
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
        featureFlags: [FEATURE_FLAGS.INSIGHT_CHART_SUGGESTIONS],
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
export const TrendsLineWithSuggestions: Story = createInsightStory(__trendsLineMulti as any, 'edit')
TrendsLineWithSuggestions.parameters = {
    ...meta.parameters,
    testOptions: {
        ...meta.parameters?.testOptions,
        waitForSelector: '[data-attr=chart-display-suggestions]',
    },
}

export const TrendsNumberWithSuggestions: Story = createInsightStory(__trendsNumber as any, 'edit')
TrendsNumberWithSuggestions.parameters = {
    ...meta.parameters,
    testOptions: {
        ...meta.parameters?.testOptions,
        waitForSelector: '[data-attr=chart-display-suggestions]',
    },
}
/* eslint-enable @typescript-eslint/no-var-requires */
