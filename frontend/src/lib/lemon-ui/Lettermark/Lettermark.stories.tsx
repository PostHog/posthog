import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { range } from 'lib/utils'

import { Lettermark, LettermarkColor, LettermarkProps } from './Lettermark'

type Story = StoryObj<typeof Lettermark>
const meta: Meta<typeof Lettermark> = {
    title: 'Lemon UI/Lettermark',
    component: Lettermark,
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

const Template: StoryFn<typeof Lettermark> = (props: LettermarkProps) => {
    return <Lettermark {...props} />
}

export const Base: Story = Template.bind({})
Base.args = { name: 'Athena' }

export const Overview = (): JSX.Element => {
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
                    {range(20).map((x) => (
                        <Lettermark key={x} index={x} name={x + 1} />
                    ))}
                </div>
            </div>
        </div>
    )
}

export const String: Story = Template.bind({})
String.args = { name: 'Athena' }

export const Number: Story = Template.bind({})
Number.args = { name: 42 }

export const Unknown: Story = Template.bind({})
Unknown.args = { name: null }

export const Gray: Story = Template.bind({})
Gray.args = { name: 5, color: LettermarkColor.Gray }

export const ExtraSmall: Story = Template.bind({})
ExtraSmall.args = { name: 'Xtra', size: 'xsmall' }

export const ExtraLarge: Story = Template.bind({})
ExtraLarge.args = { name: 'Xtra', size: 'xlarge' }
