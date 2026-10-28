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

const FIXED_THRESHOLDS = { likely_threshold: 0.6, possible_threshold: 0.2, base_rate: null }

export const Bimodal: Story = {
    args: {
        buckets: USERS_PER_DECILE.map((users, decile) => ({ lower: decile / 10, users })),
        thresholds: FIXED_THRESHOLDS,
    },
}

export const RareTarget: Story = {
    args: {
        buckets: [940, 31, 12, 6, 4, 3, 2, 1, 1, 0].map((users, decile) => ({ lower: decile / 10, users })),
        thresholds: { likely_threshold: 0.045, possible_threshold: 0.015, base_rate: 0.015 },
    },
}

export const SingleBucket: Story = {
    args: {
        buckets: Array.from({ length: 10 }, (_, decile) => ({ lower: decile / 10, users: decile === 9 ? 128 : 0 })),
        thresholds: FIXED_THRESHOLDS,
    },
}
