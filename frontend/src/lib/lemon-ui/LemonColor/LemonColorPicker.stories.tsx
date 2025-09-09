import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { DataColorToken } from 'lib/colors'

import { LemonButton } from '../LemonButton'
import { LemonColorPicker } from './LemonColorPicker'

type Story = StoryObj<typeof LemonColorPicker>
const meta: Meta<typeof LemonColorPicker> = {
    title: 'Lemon UI/Lemon Color/Lemon Color Picker',
    component: LemonColorPicker,
    tags: ['autodocs'],
}
export default meta

const colorTokens: DataColorToken[] = Array.from({ length: 15 }, (_, i) => `preset-${i + 1}` as DataColorToken)
const colors = ['#0000ff', '#00ff00', '#ff0000', '#000000', '#ffffff']

export const Default: Story = {
    render: () => {
        // eslint-disable-next-line react-hooks/rules-of-hooks
        const [colorToken, setColorToken] = useState<DataColorToken>('preset-1')
        return (
            <LemonColorPicker
                colorTokens={colorTokens}
                selectedColorToken={colorToken}
                onSelectColorToken={setColorToken}
            />
        )
    },
}

export const ShowCustomColor: Story = {
    render: () => {
        // eslint-disable-next-line react-hooks/rules-of-hooks
        const [color, setColor] = useState('#00ffff')
        return <LemonColorPicker colors={colors} selectedColor={color} onSelectColor={setColor} showCustomColor />
    },
}

export const HideDropdown: Story = {
    render: () => {
        // eslint-disable-next-line react-hooks/rules-of-hooks
        const [colorToken, setColorToken] = useState<DataColorToken>('preset-1')
        return (
            <LemonColorPicker
                colorTokens={colorTokens}
                selectedColorToken={colorToken}
                onSelectColorToken={setColorToken}
                hideDropdown
            />
        )
    },
}

export const CustomButton: Story = {
    render: () => {
        // eslint-disable-next-line react-hooks/rules-of-hooks
        const [colorToken, setColorToken] = useState<DataColorToken>('preset-1')
        return (
            <LemonColorPicker
                colorTokens={colorTokens}
                selectedColorToken={colorToken}
                onSelectColorToken={setColorToken}
                customButton={<LemonButton>Customize color</LemonButton>}
            />
        )
    },
}
