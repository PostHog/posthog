import type { Meta, StoryObj } from '@storybook/react'

import { TypesafeSuggestButton, TypesafeSuggestButtonProps } from './TypesafeSuggestButton'

type Story = StoryObj<TypesafeSuggestButtonProps>
const meta: Meta<TypesafeSuggestButtonProps> = {
    title: 'Components/TypesafeSuggestButton',
    component: TypesafeSuggestButton,
    args: {
        label: 'Suggest a title',
        dataAttr: 'story-typesafe-suggest',
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
