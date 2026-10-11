import { Meta, StoryObj } from '@storybook/react'

import { ProbabilityHistogram } from './ProbabilityHistogram'

const meta: Meta<typeof ProbabilityHistogram> = {
    title: 'Products/Autoresearch/Probability histogram',
    component: ProbabilityHistogram,
    tags: ['autodocs'],
}
export default meta
type Story = StoryObj<typeof ProbabilityHistogram>

const USERS_PER_DECILE = [30, 1, 4, 3, 0, 1, 3, 2, 3, 81]

export const Bimodal: Story = {
    args: {
        buckets: USERS_PER_DECILE.map((users, decile) => ({ lower: decile / 10, users })),
    },
}

export const SingleBucket: Story = {
    args: {
        buckets: Array.from({ length: 10 }, (_, decile) => ({ lower: decile / 10, users: decile === 9 ? 128 : 0 })),
    },
}
