import type { Meta, StoryObj } from '@storybook/react'

import { EmailDisplayNameSettings } from './EmailDisplayNameSettings'

const meta: Meta<typeof EmailDisplayNameSettings> = {
    title: 'Scenes-App/Support/EmailDisplayNameSettings',
    component: EmailDisplayNameSettings,
    parameters: { layout: 'padded', viewMode: 'story', testOptions: { snapshotBrowsers: [] } },
}
export default meta

type Story = StoryObj<typeof EmailDisplayNameSettings>

export const Saved: Story = {
    args: {
        configId: 'support-channel',
        value: 'Acme Support',
        savedValue: 'Acme Support',
        savingConfigId: null,
        onChange: () => {},
        onSave: () => {},
    },
}

export const Edited: Story = {
    args: {
        ...Saved.args,
        value: 'Acme Customer Success',
    },
}
