import React, { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonBubble, LemonBubbleProps } from './LemonBubble'
import { LemonButton } from '../LemonButton'

export default {
    title: 'Lemon UI/Lemon Bubble',
    component: LemonBubble,
} as ComponentMeta<typeof LemonBubble>

const Template: ComponentStory<typeof LemonBubble> = ({ count, ...props }: LemonBubbleProps) => {
    const [countOverride, setCount] = useState(count)

    return (
        <>
            <div className="flex space-x-4">
                Count: <LemonBubble count={countOverride} {...props} />
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

export const Positioning: ComponentStory<typeof LemonBubble> = () => {
    return (
        <div className="space-y-4">
            <LemonButton outlined style={{ position: 'relative' }}>
                top-right
                <LemonBubble count={4} position="top-right" />
            </LemonButton>

            <LemonButton outlined style={{ position: 'relative' }}>
                top-left
                <LemonBubble count={4} position="top-left" />
            </LemonButton>

            <LemonButton outlined style={{ position: 'relative' }}>
                bottom-right
                <LemonBubble count={4} position="bottom-right" />
            </LemonButton>

            <LemonButton outlined style={{ position: 'relative' }}>
                bottom-left
                <LemonBubble count={4} position="bottom-left" />
            </LemonButton>
        </div>
    )
}

export const Sizes: ComponentStory<typeof LemonBubble> = () => {
    return (
        <div className="flex space-x-2 items-center">
            <span>small:</span>
            <LemonBubble count={4} size="small" />
            <span>medium:</span>
            <LemonBubble count={4} size="medium" />
            <span>large:</span>
            <LemonBubble count={4} size="large" />
        </div>
    )
}
