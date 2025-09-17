import { Meta, StoryObj } from '@storybook/react'

import { LemonColorButton } from './LemonColorButton'

type Story = StoryObj<typeof LemonColorButton>
const meta: Meta<typeof LemonColorButton> = {
    title: 'Lemon UI/Lemon Color/Lemon Color Button',
    component: LemonColorButton,
    tags: ['autodocs'],
}
export default meta

export const Default: Story = {
    render: () => <LemonColorButton colorToken="preset-1" />,
}

export const Tertiary: Story = {
    render: () => <LemonColorButton type="tertiary" colorToken="preset-1" />,
}

export const Small: Story = {
    render: () => <LemonColorButton size="small" colorToken="preset-1" />,
}

export const CustomColor: Story = {
    render: () => <LemonColorButton color="#ff0000" />,
}

export const UnsetColor: Story = {
    render: () => <LemonColorButton color={null} />,
}

export const CustomTheme: Story = {
    render: () => <LemonColorButton colorToken="preset-1" themeId={2} />,
}

export const HiddenColorDescription: Story = {
    render: () => <LemonColorButton colorToken="preset-1" hideColorDescription />,
}
