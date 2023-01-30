import { ComponentMeta, ComponentStory } from '@storybook/react'
import { Lettermark, LettermarkColor, LettermarkProps } from './Lettermark'
import { range } from 'lib/utils'

export default {
    title: 'Lemon UI/Lettermark',
    component: Lettermark,
    parameters: {
        docs: {
            description: {
                component:
                    'Lettermarks are used as visual, icon-like representations of actors (project members, organizations, query steps, cohort criteria groups, etc) in the product. Lettermarks should vary between the 8 variants we have shown below. Ideally the same colour is not placed next to each other',
            },
        },
    },
} as ComponentMeta<typeof Lettermark>

const Template: ComponentStory<typeof Lettermark> = (props: LettermarkProps) => {
    return <Lettermark {...props} />
}

export const Base = Template.bind({})
Base.args = { name: 'Athena' }

export const Overview = (): JSX.Element => {
    return (
        <div className="space-y-2">
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
                <div className="space-x-1">
                    {range(20).map((x) => (
                        <Lettermark key={x} index={x} name={x + 1} />
                    ))}
                </div>
            </div>
        </div>
    )
}

export const String = Template.bind({})
String.args = { name: 'Athena' }

export const Number = Template.bind({})
Number.args = { name: 42 }

export const Unknown = Template.bind({})
Unknown.args = { name: null }

export const Gray = Template.bind({})
Gray.args = { name: 5, color: LettermarkColor.Gray }
