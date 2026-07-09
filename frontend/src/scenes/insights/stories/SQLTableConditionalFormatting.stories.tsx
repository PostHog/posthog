import { Meta, StoryObj } from '@storybook/react'

import { createInsightStory } from 'scenes/insights/__mocks__/createInsightScene'

import { mswDecorator } from '~/mocks/browser'

import __sqlTableConditionalFormatting from '../../../mocks/fixtures/api/projects/team_id/insights/sqlTableConditionalFormatting.json'

type Story = StoryObj<{}>
const meta: Meta = {
    title: 'Scenes-App/Insights/SQLTableConditionalFormatting',
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
                '/api/projects/:team_id/groups_types': [],
            },
        }),
    ],
}

export default meta

// Table with conditional formatting rules that paint cells with light pastel backgrounds. In dark
// mode the cell text must stay dark enough to read against those backgrounds rather than inheriting
// the theme's near-white text color. Storybook snapshots both light and dark themes automatically.
/* eslint-disable @typescript-eslint/no-var-requires */
export const SQLTableConditionalFormatting: Story = createInsightStory(__sqlTableConditionalFormatting as any)
SQLTableConditionalFormatting.parameters = {
    ...meta.parameters,
    testOptions: {
        ...meta.parameters?.testOptions,
        waitForSelector: '.DataVisualizationTable',
    },
}
/* eslint-enable @typescript-eslint/no-var-requires */
