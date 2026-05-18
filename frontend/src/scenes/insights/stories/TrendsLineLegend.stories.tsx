import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'

import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'
import { LegendPosition } from '~/queries/schema/schema-general'

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Scenes-App/Insights/TrendsLineLegend',
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

const fixture = require('../../../mocks/fixtures/api/projects/team_id/insights/trendsLineBreakdown.json')

const waitForCanvas = {
    ...meta.parameters,
    testOptions: {
        ...meta.parameters?.testOptions,
        waitForSelector: '[data-attr=trend-line-graph] > canvas',
    },
}

export const LegendRight: Story = createInsightStory(fixture, 'view', true, { legendPosition: LegendPosition.Right })
LegendRight.parameters = waitForCanvas

export const LegendBottom: Story = createInsightStory(fixture, 'view', true, { legendPosition: LegendPosition.Bottom })
LegendBottom.parameters = waitForCanvas

export const LegendTop: Story = createInsightStory(fixture, 'view', true, { legendPosition: LegendPosition.Top })
LegendTop.parameters = waitForCanvas

export const LegendLeft: Story = createInsightStory(fixture, 'view', true, { legendPosition: LegendPosition.Left })
LegendLeft.parameters = waitForCanvas

/* eslint-enable @typescript-eslint/no-var-requires */
