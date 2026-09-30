import type { Meta, StoryObj } from '@storybook/react'

import { TrustedRelaySenderSettings } from './TrustedRelaySenderSettings'

const meta: Meta<typeof TrustedRelaySenderSettings> = {
    title: 'Scenes-App/Support/TrustedRelaySenderSettings',
    component: TrustedRelaySenderSettings,
    parameters: { layout: 'padded', viewMode: 'story' },
}
export default meta

type Story = StoryObj<typeof TrustedRelaySenderSettings>

export const Empty: Story = {
    args: {
        configId: 'support-channel',
        value: '',
        savedValue: '',
        savingConfigId: null,
        onChange: () => {},
        onSave: () => {},
    },
}

export const Edited: Story = {
    args: {
        ...Empty.args,
        value: 'relay@example.com',
    },
}

export const Saving: Story = {
    args: {
        ...Edited.args,
        savingConfigId: 'support-channel',
    },
    parameters: {
        testOptions: {
            // The save button spinner is the state under test, so it never disappears.
            waitForLoadersToDisappear: false,
        },
    },
}
