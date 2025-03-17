import { Meta, StoryObj } from '@storybook/react'
import { DataColorToken } from 'lib/colors'

import { LemonColorGlyph as LemonColorGlyphComponent } from './LemonColorGlyph'
import { LemonColorList as LemonColorListComponent } from './LemonColorList'

type Story = StoryObj<typeof LemonColorGlyphComponent>
const meta: Meta<typeof LemonColorGlyphComponent> = {
    title: 'Lemon UI/Lemon Color/Lemon Color List',
    component: LemonColorGlyphComponent,
    tags: ['autodocs'],
}
export default meta

const colorTokens: DataColorToken[] = Array.from({ length: 15 }, (_, i) => `preset-${i + 1}` as DataColorToken)

export const Default: Story = {
    render: () => (
        <>
            <LemonColorListComponent
                colorTokens={colorTokens}
                selectedColorToken={colorTokens[3]}
                onClick={(colorToken) => {
                    alert(colorToken)
                }}
            />
        </>
    ),
}

export const CustomColors: Story = {
    render: () => (
        <LemonColorListComponent
            colors={['#ff0000', '#00ff00', '#0000ff']}
            selectedColor="#00ff00"
            onClick={(color) => {
                alert(color)
            }}
        />
    ),
}
