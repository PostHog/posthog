import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { LemonBadge, LemonBadgeNumberProps } from './LemonBadge'

type Story = StoryObj<LemonBadgeNumberProps>
const meta: Meta<LemonBadgeNumberProps> = {
    title: 'Lemon UI/Lemon Badge/Lemon Badge Number',
    component: LemonBadge.Number as any,
    tags: ['autodocs'],
    render: ({ count, ...props }) => {
        const [countOverride, setCount] = useState(count)

        return (
            <>
                <div className="flex items-center min-h-6">
                    <div>Count: </div>
                    <LemonBadge.Number count={countOverride} {...props} />
                </div>
                <br />
                <div className="flex deprecated-space-x-1">
                    <LemonButton type="primary" onClick={() => setCount((countOverride || 0) + 1)}>
                        Increment
                    </LemonButton>
                    <LemonButton type="secondary" onClick={() => setCount((countOverride || 0) - 1)}>
                        Decrement
                    </LemonButton>
                </div>
            </>
        )
    },
}
export default meta

export const Standard: Story = {
    args: { count: 1 },
}

export const MultipleDigits: Story = {
    args: { count: 975, maxDigits: 3 },
}

export const ShowZero: Story = {
    args: { count: 0, showZero: true },
}
