import type { Meta, StoryObj } from '@storybook/react'

import { SuggestMetadataButton, SuggestMetadataButtonProps } from './SuggestMetadataButton'

type Story = StoryObj<SuggestMetadataButtonProps>
const meta: Meta<SuggestMetadataButtonProps> = {
    title: 'Components/SuggestMetadataButton',
    component: SuggestMetadataButton,
    args: {
        label: 'Suggest a title',
        dataAttr: 'story-suggest-metadata',
        onClick: () => {},
    },
    tags: ['autodocs'],
}
export default meta

export const Default: Story = {}

export const Loading: Story = {
    args: { loading: true },
}

export const Disabled: Story = {
    args: { disabledReason: 'Save the insight first' },
}
