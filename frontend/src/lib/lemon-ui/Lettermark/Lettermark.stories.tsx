import type { Meta, StoryObj } from '@storybook/react'

import { range } from 'lib/utils'

import { Lettermark, LettermarkColor, LettermarkProps, NUM_LETTERMARK_STYLES } from './Lettermark'

type Story = StoryObj<LettermarkProps>
const meta: Meta<LettermarkProps> = {
    title: 'Lemon UI/Lettermark',
    component: Lettermark as any,
    parameters: {
        docs: {
            description: {
                component:
                    'Lettermarks are used as visual, icon-like representations of actors (project members, organizations, query steps, cohort criteria groups, etc) in the product. Lettermarks should vary between the 8 variants we have shown below. Ideally the same colour is not placed next to each other',
            },
        },
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
    tags: ['autodocs'],
}
export default meta

export const Base: Story = {
    args: { name: 'Athena' },
}

export const Overview: Story = {
    render: () => {
        return (
            <div className="deprecated-space-y-2">
                <div>
                    <Lettermark name="Ben" /> Text
                </div>
                <div>
                    <Lettermark name={42} /> Number
                </div>
                <div>
                    <Lettermark name={null} /> Missing
                </div>

                <div>
                    <p>Color based on index</p>
                    <div className="deprecated-space-x-1">
                        {range(NUM_LETTERMARK_STYLES).map((x) => (
                            <Lettermark key={x} index={x} name={x + 1} />
                        ))}
                    </div>
                </div>
            </div>
        )
    },
}

export const String: Story = {
    args: { name: 'Athena' },
}

export const Number: Story = {
    args: { name: 42 },
}

export const Unknown: Story = {
    args: { name: null },
}

export const Gray: Story = {
    args: { name: 5, color: LettermarkColor.Gray },
}

export const ExtraSmall: Story = {
    args: { name: 'Xtra', size: 'xsmall' },
}

export const ExtraLarge: Story = {
    args: { name: 'Xtra', size: 'xlarge' },
}
