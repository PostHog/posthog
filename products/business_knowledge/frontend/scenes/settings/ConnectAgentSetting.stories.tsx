import type { Meta, StoryObj } from '@storybook/react'

import { ConnectAgentSetting } from './ConnectAgentSetting'

const meta: Meta<typeof ConnectAgentSetting> = {
    title: 'Scenes-App/BusinessKnowledge/ConnectAgentSetting',
    component: ConnectAgentSetting,
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        // Used by one settings section, so the story checks that it renders and adds no visual baseline.
        testOptions: { snapshotBrowsers: [] },
    },
}

export default meta

type Story = StoryObj<typeof ConnectAgentSetting>

export const Default: Story = {}
