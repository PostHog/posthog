import { samplePersonProperties, sampleRetentionPeopleResponse } from 'scenes/insights/__mocks__/insight.mocks'

import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@storybook/testing-library'

import { App } from 'scenes/App'
import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

type Story = StoryObj<typeof App>
const meta: Meta = {
    title: 'Scenes-App/Insights/User Paths',
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

// User Paths

export const UserPaths: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/userPaths.json')
)
UserPaths.parameters = {
    testOptions: {
        waitForSelector: ['[data-attr=path-node-card-button]:nth-child(7)', '.Paths__canvas'],
    },
}
// The Paths component uses useResizeObserver to measure canvasWidth, then destroys
// and recreates the SVG when it changes. This causes a race condition where the SVG
// width may not have stabilized before the snapshot is taken. Wait for it to settle.
const waitForPathsCanvasToStabilize: NonNullable<Story['play']> = async ({ canvasElement }) => {
    let lastWidth = 0
    await waitFor(
        () => {
            const svg = canvasElement.querySelector('.Paths__canvas')
            const currentWidth = svg ? svg.getBoundingClientRect().width : 0
            if (currentWidth === 0 || currentWidth !== lastWidth) {
                lastWidth = currentWidth
                throw new Error('SVG width not yet stable')
            }
        },
        { timeout: 3000, interval: 200 }
    )
}
UserPaths.play = waitForPathsCanvasToStabilize

export const UserPathsEdit: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/userPaths.json'),
    'edit'
)
UserPathsEdit.parameters = {
    testOptions: {
        waitForSelector: ['[data-attr=path-node-card-button]:nth-child(7)', '.Paths__canvas'],
    },
}
UserPathsEdit.play = waitForPathsCanvasToStabilize

export const UserPathsEditViewports: Story = createInsightStory(
    require('../../mocks/fixtures/api/projects/team_id/insights/userPaths.json'),
    'edit'
)
UserPathsEditViewports.parameters = {
    testOptions: {
        waitForSelector: ['[data-attr=path-node-card-button]:nth-child(7)', '.Paths__canvas'],
        viewportWidths: ['medium', 'wide', 'superwide'],
    },
}
UserPathsEditViewports.play = waitForPathsCanvasToStabilize
/* eslint-enable @typescript-eslint/no-var-requires */
