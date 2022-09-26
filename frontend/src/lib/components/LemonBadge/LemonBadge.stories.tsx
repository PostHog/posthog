import React, { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonBadge, LemonBadgeProps } from './LemonBadge'
import { LemonButton } from '../LemonButton'

export default {
    title: 'Lemon UI/Lemon Badge',
    component: LemonBadge,
} as ComponentMeta<typeof LemonBadge>

const Template: ComponentStory<typeof LemonBadge> = ({ count, ...props }: LemonBadgeProps) => {
    const [countOverride, setCount] = useState(count as number)

    return (
        <>
            <div className="flex space-x-4">
                Count: <LemonBadge count={countOverride} {...props} />
            </div>
            <br />
            <div className="flex space-x-4">
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

export const Standard = Template.bind({})
Standard.args = { count: 1 }

export const OverNine = Template.bind({})
OverNine.args = { count: 10 }

export const ShowZero = Template.bind({})
ShowZero.args = { count: 0, showZero: true }

export const Positioning: ComponentStory<typeof LemonBadge> = () => {
    return (
        <div className="space-y-4">
            <LemonButton type="secondary">
                top-right
                <LemonBadge count={4} position="top-right" />
            </LemonButton>

            <LemonButton type="secondary">
                top-left
                <LemonBadge count={4} position="top-left" />
            </LemonButton>

            <LemonButton type="secondary">
                bottom-right
                <LemonBadge count={4} position="bottom-right" />
            </LemonButton>

            <LemonButton type="secondary">
                bottom-left
                <LemonBadge count={4} position="bottom-left" />
            </LemonButton>
        </div>
    )
}

export const Sizes: ComponentStory<typeof LemonBadge> = () => {
    return (
        <div className="flex space-x-2 items-center">
            <span>small:</span>
            <LemonBadge count={4} size="small" />
            <span>medium:</span>
            <LemonBadge count={4} size="medium" />
            <span>large:</span>
            <LemonBadge count={4} size="large" />
        </div>
    )
}
