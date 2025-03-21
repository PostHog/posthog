import { Meta, StoryObj } from '@storybook/react'

import { LemonColorGlyph } from './LemonColorGlyph'

type Story = StoryObj<typeof LemonColorGlyph>
const meta: Meta<typeof LemonColorGlyph> = {
    title: 'Lemon UI/Lemon Color/Lemon Color Glyph',
    component: LemonColorGlyph,
    tags: ['autodocs'],
}
export default meta

export const Default: Story = {
    render: () => <LemonColorGlyph colorToken="preset-1" />,
}

export const Small: Story = {
    render: () => <LemonColorGlyph size="small" colorToken="preset-1" />,
}

export const CustomColor: Story = {
    render: () => <LemonColorGlyph color="#ff0000" />,
}

export const UnsetColor: Story = {
    render: () => <LemonColorGlyph color={null} />,
}

export const CustomTheme: Story = {
    render: () => <LemonColorGlyph colorToken="preset-1" themeId={2} />,
}
