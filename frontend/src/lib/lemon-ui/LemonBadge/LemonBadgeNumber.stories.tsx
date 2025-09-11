import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { LemonBadge, LemonBadgeNumberProps } from './LemonBadge'

type Story = StoryObj<typeof LemonBadge.Number>
const meta: Meta<typeof LemonBadge.Number> = {
    title: 'Lemon UI/Lemon Badge/Lemon Badge Number',
    component: LemonBadge.Number,
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof LemonBadge.Number> = ({ count, ...props }: LemonBadgeNumberProps) => {
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
}

export const Standard: Story = Template.bind({})
Standard.args = { count: 1 }

export const MultipleDigits: Story = Template.bind({})
MultipleDigits.args = { count: 975, maxDigits: 3 }

export const ShowZero: Story = Template.bind({})
ShowZero.args = { count: 0, showZero: true }
