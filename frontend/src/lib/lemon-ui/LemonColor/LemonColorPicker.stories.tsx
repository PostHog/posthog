import { Meta, StoryObj } from '@storybook/react'
import { DataColorToken } from 'lib/colors'

import { LemonColorPicker } from './LemonColorPicker'

type Story = StoryObj<typeof LemonColorPicker>
const meta: Meta<typeof LemonColorPicker> = {
    title: 'Lemon UI/Lemon Color/Lemon Color Picker',
    component: LemonColorPicker,
    tags: ['autodocs'],
}
export default meta

const colorTokens: DataColorToken[] = Array.from({ length: 15 }, (_, i) => `preset-${i + 1}` as DataColorToken)

export const Default: Story = {
    render: () => <LemonColorPicker colorTokens={colorTokens} onClick={(value) => alert(value)} />,
}

export const ShowCustomColor: Story = {
    render: () => <LemonColorPicker colorTokens={colorTokens} onClick={(value) => alert(value)} showCustomColor />,
}

export const HideDropdown: Story = {
    render: () => <LemonColorPicker colorTokens={colorTokens} onClick={(value) => alert(value)} hideDropdown />,
}
