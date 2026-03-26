import type { Meta, StoryObj } from '@storybook/react'

import { LemonCard, LemonCardProps } from './LemonCard'

type Story = StoryObj<LemonCardProps>
const meta: Meta<LemonCardProps> = {
    title: 'Lemon UI/Lemon Card',
    component: LemonCard as any,
    tags: ['autodocs'],
    render: (props) => {
        return (
            <div>
                <LemonCard {...props}>
                    <span>Tis a lemon card</span>
                </LemonCard>
            </div>
        )
    },
}
export default meta

export const Default: Story = {
    args: {},
}

export const Focused: Story = {
    args: { focused: true },
}

export const HoverEffect: Story = {
    args: { hoverEffect: true },
}

export const Closeable: Story = {
    args: { closeable: true },
}
