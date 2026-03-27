import { Meta, StoryObj } from '@storybook/react'

import { LemonProgress, LemonProgressProps } from './LemonProgress'

const meta: Meta<LemonProgressProps> = {
    title: 'Lemon UI/Lemon Progress',
    component: LemonProgress,
    args: {
        percent: 30,
    },
    tags: ['autodocs'],
}
type Story = StoryObj<LemonProgressProps>
export default meta

export const Variations: Story = {
    render: () => {
        return (
            <div className="min-w-120">
                <LemonProgress percent={30} />
                <LemonProgress percent={75} strokeColor="var(--warning)" />
                <LemonProgress percent={50} size="large" strokeColor="purple" />
                <LemonProgress percent={NaN} />
                <LemonProgress percent={500} />
            </div>
        )
    },
}
