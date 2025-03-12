import { Meta, StoryObj } from '@storybook/react'
import { dataColorVars, getColorVar } from 'lib/colors'

import { LemonColorGlyph } from './LemonColorGlyph'

type Story = StoryObj<typeof LemonColorGlyph>
const meta: Meta<typeof LemonColorGlyph> = {
    title: 'Lemon UI/Lemon Color Glyph',
    component: LemonColorGlyph,
    tags: ['autodocs'],
}
export default meta

export const Default: Story = {
    render: () => (
        <div className="flex gap-1 flex-wrap">
            {dataColorVars.map((color) => (
                <LemonColorGlyph key={color} color={getColorVar(color)} />
            ))}
            <LemonColorGlyph color={null} />
        </div>
    ),
}
