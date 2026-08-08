import type { Meta, StoryObj } from '@storybook/react'

import { PropertyFilterType, PropertyOperator } from '~/types'

import { OverConstrainedFiltersBanner } from './OverConstrainedFiltersBanner'

type Story = StoryObj<typeof OverConstrainedFiltersBanner>
const meta: Meta<typeof OverConstrainedFiltersBanner> = {
    title: 'Filters/OverConstrainedFiltersBanner',
    component: OverConstrainedFiltersBanner,
}
export default meta

// Three path filters on one series can never all match, so the insight returns nothing.
export const OverConstrained: Story = {
    args: {
        properties: [
            {
                type: PropertyFilterType.Event,
                key: '$current_url',
                operator: PropertyOperator.IContains,
                value: '/pricing',
            },
            {
                type: PropertyFilterType.Event,
                key: '$current_url',
                operator: PropertyOperator.IContains,
                value: '/blog',
            },
            {
                type: PropertyFilterType.Event,
                key: '$current_url',
                operator: PropertyOperator.IContains,
                value: '/docs',
            },
        ],
    },
}
