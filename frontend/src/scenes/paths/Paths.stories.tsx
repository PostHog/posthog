import { Meta, StoryObj } from '@storybook/react'

import { InsightVizStory } from 'scenes/insights/__mocks__/createInsightVizStory'

import __userPaths from '~/mocks/fixtures/api/projects/team_id/insights/userPaths.json'

import { Paths } from './Paths'

type Story = StoryObj<{}>

const meta: Meta = {
    title: 'Insights/Paths',
    component: Paths,
    parameters: {
        layout: 'centered',
        mockDate: '2022-03-11',
        testOptions: {
            snapshotBrowsers: ['chromium'],
            // The Paths component removes data-stable from its canvas while (re)building the SVG
            // and re-adds it once settled, so this waits out the resize-observer churn.
            waitForSelector: ['[data-attr=path-node-card-button]', '[data-attr=paths-viz][data-stable]'],
        },
    },
}
export default meta

export const UserPaths: Story = {
    render: () => (
        <InsightVizStory insight={__userPaths as any} width={1000}>
            {/* Paths sizes its canvas from the container, so it needs explicit dimensions */}
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <div style={{ height: 576 }}>
                <Paths />
            </div>
        </InsightVizStory>
    ),
}
