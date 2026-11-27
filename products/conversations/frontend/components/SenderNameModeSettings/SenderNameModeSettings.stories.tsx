import type { Meta, StoryObj } from '@storybook/react'

import { SenderNameModeSettings } from './SenderNameModeSettings'

const meta: Meta<typeof SenderNameModeSettings> = {
    title: 'Scenes-App/Support/SenderNameModeSettings',
    component: SenderNameModeSettings,
    parameters: { layout: 'padded', viewMode: 'story', testOptions: { snapshotBrowsers: [] } },
}
export default meta

type Story = StoryObj<typeof SenderNameModeSettings>

export const ChannelName: Story = {
    args: {
        configId: 'support-channel',
        value: 'channel',
        displayName: 'Acme Support',
        savingConfigId: null,
        onChange: () => {},
    },
}

export const AgentName: Story = {
    args: {
        ...ChannelName.args,
        value: 'agent',
    },
}
