import { Meta, StoryObj } from '@storybook/react'
import { DataColorToken, dataColorVars, getColorVar } from 'lib/colors'

import { LemonColorButton as LemonColorButtonComponent } from './LemonColorButton'
import { LemonColorGlyph as LemonColorGlyphComponent } from './LemonColorGlyph'

type Story = StoryObj<typeof LemonColorGlyphComponent>
const meta: Meta<typeof LemonColorGlyphComponent> = {
    title: 'Lemon UI/Lemon Color',
    component: LemonColorGlyphComponent,
    tags: ['autodocs'],
}
export default meta

export const LemonColorGlyph: Story = {
    render: () => (
        <div className="flex gap-1 flex-wrap">
            <LemonColorGlyphComponent color="#ff0000" />
            <LemonColorGlyphComponent color="#00ff00" />
            <LemonColorGlyphComponent color="#0000ff" />
            {Array.from({ length: 15 }, (_, i) => `preset-${i + 1}`).map((token) => (
                <LemonColorGlyphComponent key={token} colorToken={token as DataColorToken} />
            ))}
            <LemonColorGlyphComponent color={null} />
        </div>
    ),
}

export const LemonColorButton: Story = {
    render: () => (
        <div className="flex gap-1 flex-wrap">
            <LemonColorButtonComponent color={getColorVar(dataColorVars[0])} />
            <LemonColorButtonComponent type="tertiary" color={getColorVar(dataColorVars[0])} />
        </div>
    ),
}
