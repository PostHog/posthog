import { Meta, StoryObj } from '@storybook/react'

import { LemonColorPicker } from './LemonColorPicker'

type Story = StoryObj<typeof LemonColorPicker>
const meta: Meta<typeof LemonColorPicker> = {
    title: 'Lemon UI/Lemon Color/Lemon Color Picker',
    component: LemonColorPicker,
    tags: ['autodocs'],
}
export default meta

export const Default: Story = {
    render: () => <LemonColorPicker />,
}

export const ShowCustomColor: Story = {
    render: () => <LemonColorPicker showCustomColor />,
}

export const hideDropdown: Story = {
    render: () => <LemonColorPicker hideDropdown />,
}
