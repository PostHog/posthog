import { Meta, StoryObj } from '@storybook/react'
import { DataColorToken } from 'lib/colors'

import { LemonColorList } from './LemonColorList'

type Story = StoryObj<typeof LemonColorList>
const meta: Meta<typeof LemonColorList> = {
    title: 'Lemon UI/Lemon Color/Lemon Color List',
    component: LemonColorList,
    tags: ['autodocs'],
}
export default meta

const colorTokens: DataColorToken[] = Array.from({ length: 15 }, (_, i) => `preset-${i + 1}` as DataColorToken)

export const Default: Story = {
    render: () => {
        return (
            <LemonColorList
                colorTokens={colorTokens}
                selectedColorToken={colorTokens[3]}
                onClick={(colorToken) => {
                    alert(colorToken)
                }}
            />
        )
    },
}

export const CustomColors: Story = {
    render: () => (
        <LemonColorList
            colors={['#ff0000', '#00ff00', '#0000ff']}
            selectedColor="#00ff00"
            onClick={(color) => {
                alert(color)
            }}
        />
    ),
}

export const CustomTheme: Story = {
    render: () => (
        <LemonColorList
            colorTokens={colorTokens}
            selectedColor={colorTokens[3]}
            themeId={2}
            onClick={(color) => {
                alert(color)
            }}
        />
    ),
}
