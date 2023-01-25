import { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonBadge, LemonBadgeNumberProps } from './LemonBadge'
import { LemonButton } from '../LemonButton'

export default {
    title: 'Lemon UI/Lemon Badge/Lemon Badge Number',
    component: LemonBadge.Number,
    parameters: {},
} as ComponentMeta<typeof LemonBadge.Number>

const Template: ComponentStory<typeof LemonBadge.Number> = ({ count, ...props }: LemonBadgeNumberProps) => {
    const [countOverride, setCount] = useState(count)

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
