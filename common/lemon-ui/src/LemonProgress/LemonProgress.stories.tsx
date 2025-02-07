import { Meta, StoryFn } from '@storybook/react'

import { LemonProgress } from './LemonProgress'

const meta: Meta<typeof LemonProgress> = {
    title: 'Lemon UI/Lemon Progress',
    component: LemonProgress,
    args: {
        percent: 30,
    },
    tags: ['autodocs'],
}
export default meta

export const Variations: StoryFn<typeof LemonProgress> = () => {
    return (
        <div className="min-w-120">
            <LemonProgress percent={30} />
            <LemonProgress percent={75} strokeColor="var(--warning)" />
            <LemonProgress percent={50} size="large" strokeColor="purple" />
            <LemonProgress percent={NaN} />
            <LemonProgress percent={500} />
        </div>
    )
}
