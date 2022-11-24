import { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonBadge, LemonBadgeNumberProps } from './LemonBadge'
import { LemonButton } from '../LemonButton'

export default {
    title: 'Lemon UI/Lemon Badge',
    component: LemonBadge,
    parameters: {
        chromatic: { disableSnapshot: false },
    },
} as ComponentMeta<typeof LemonBadge.Number>

const Template: ComponentStory<typeof LemonBadge.Number> = ({ count, ...props }: LemonBadgeNumberProps) => {
    const [countOverride, setCount] = useState(count as number)

    return (
        <>
            <div className="flex items-center min-h-6">
                <div>Count: </div>
                <LemonBadge.Number count={countOverride} {...props} />
            </div>
            <br />
            <div className="flex space-x-1">
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

export const MultipleDigits = Template.bind({})
MultipleDigits.args = { count: 975, maxDigits: 3 }

export const ShowZero = Template.bind({})
ShowZero.args = { count: 0, showZero: true }

export const Positioning: ComponentStory<typeof LemonBadge.Number> = () => {
    return (
        <div className="space-y-4">
            <LemonButton type="secondary">
                top-right
                <LemonBadge.Number count={4} position="top-right" />
            </LemonButton>

            <LemonButton type="secondary">
                top-left
                <LemonBadge.Number count={4} position="top-left" />
            </LemonButton>

            <LemonButton type="secondary">
                bottom-right
                <LemonBadge.Number count={4} position="bottom-right" />
            </LemonButton>

            <LemonButton type="secondary">
                bottom-left
                <LemonBadge.Number count={4} position="bottom-left" />
            </LemonButton>
        </div>
    )
}

export const Sizes: ComponentStory<typeof LemonBadge.Number> = () => {
    return (
        <div className="flex space-x-2 items-center">
            <span>small:</span>
            <LemonBadge.Number count={4} size="small" />
            <span>medium:</span>
            <LemonBadge.Number count={4} size="medium" />
            <span>large:</span>
            <LemonBadge.Number count={4} size="large" />
        </div>
    )
}

export const Status: ComponentStory<typeof LemonBadge.Number> = () => {
    return (
        <div className="flex space-x-2 items-center">
            <span>primary:</span>
            <LemonBadge.Number count={4} status="primary" />
            <span>danger:</span>
            <LemonBadge.Number count={4} status="danger" />
            <span>muted:</span>
            <LemonBadge.Number count={4} status="muted" />
        </div>
    )
}
