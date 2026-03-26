import type { Meta, StoryObj } from '@storybook/react'

import { LemonCard, LemonCardProps } from './LemonCard'

type Story = StoryObj<typeof meta>
const meta: Meta<typeof LemonCard> = {
    title: 'Lemon UI/Lemon Card',
    component: LemonCard,
    tags: ['autodocs'],
    render: (props: LemonCardProps) => {
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
