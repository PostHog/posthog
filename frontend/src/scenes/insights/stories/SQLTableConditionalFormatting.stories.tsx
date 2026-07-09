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

// Table with a conditional-formatting rule for every default palette color, once as a light-mode
// rule and once as a dark-mode rule (the "light mode" and "dark mode" columns). Each cell shows its
// own hex on its own background, so the text must stay legible on every color. Storybook snapshots
// both light and dark themes automatically, giving us the light and dark rendering of each color.
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
