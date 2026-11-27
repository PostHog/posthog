import type { Meta, StoryObj } from '@storybook/react'

import { SenderNameTemplateSettings } from './SenderNameTemplateSettings'

const meta: Meta<typeof SenderNameTemplateSettings> = {
    title: 'Scenes-App/Support/SenderNameTemplateSettings',
    component: SenderNameTemplateSettings,
    parameters: { layout: 'padded', viewMode: 'story', testOptions: { snapshotBrowsers: [] } },
}
export default meta

type Story = StoryObj<typeof SenderNameTemplateSettings>

export const Blank: Story = {
    args: {
        configId: 'support-channel',
        value: '',
        savedValue: '',
        displayName: 'Acme Support',
        savingConfigId: null,
        onChange: () => {},
        onSave: () => {},
    },
}

export const Edited: Story = {
    args: {
        ...Blank.args,
        value: '{author_first_name} at Acme',
    },
}
