import { Meta, StoryObj } from '@storybook/react'
import { dataColorVars, getColorVar } from 'lib/colors'

import { LemonColorButton as LemonColorButtonComponent } from './LemonColorButton'
import { LemonColorGlyph as LemonColorGlyphComponent } from './LemonColorGlyph'

type Story = StoryObj<typeof LemonColorGlyph>
const meta: Meta<typeof LemonColorGlyph> = {
    title: 'Lemon UI/Lemon Color',
    component: LemonColorGlyphComponent,
    tags: ['autodocs'],
}
export default meta

export const LemonColorGlyph: Story = {
    render: () => (
        <div className="flex gap-1 flex-wrap">
            {dataColorVars.map((color) => (
                <LemonColorGlyphComponent key={color} color={getColorVar(color)} />
            ))}
            <LemonColorGlyphComponent color={null} />
        </div>
    ),
}

export const LemonColorButton: Story = {
    render: () => (
        <div className="flex gap-1 flex-wrap">
            <LemonColorButtonComponent color={getColorVar(dataColorVars[0])} />
        </div>
    ),
}
