import { Meta, StoryFn } from '@storybook/react'

import { LemonProgress, LemonProgressProps } from './LemonProgress'

// type Story = StoryObj<typeof LemonProgress>
const meta: Meta<typeof LemonProgress> = {
    title: 'Lemon UI/Lemon Progress',
    component: LemonProgress,
    args: {
        percent: 30,
    },
    tags: ['autodocs'],
}
export default meta

export const Template: StoryFn<typeof LemonProgress> = (props: LemonProgressProps) => {
    return <LemonProgress {...props} />
}
