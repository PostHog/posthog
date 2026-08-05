import { Meta, StoryObj } from '@storybook/react'

import { InsightVizStory } from 'scenes/insights/__mocks__/createInsightVizStory'

import __trendsWorldMap from '~/mocks/fixtures/api/projects/team_id/insights/trendsWorldMap.json'

import { WorldMap } from './WorldMap'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/WorldMap',
    component: WorldMap,
    parameters: {
        layout: 'centered',
        mockDate: '2022-04-05',
        testOptions: {
            snapshotBrowsers: ['chromium'],
            waitForSelector: '.WorldMap',
        },
    },
}
export default meta

export const Default: Story = {
    render: () => <InsightVizStory insight={__trendsWorldMap as any} />,
}
