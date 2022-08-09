import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonLabel, LemonLabelProps } from './LemonLabel'

export default {
    title: 'Lemon UI/Lemon Label',
    component: LemonLabel,
} as ComponentMeta<typeof LemonLabel>

const Template: ComponentStory<typeof LemonLabel> = (props: LemonLabelProps) => {
    return <LemonLabel {...props} />
}

export const Basic = Template.bind({})
Basic.args = {
    children: 'Label',
}

export const Overview = (): JSX.Element => {
    return (
        <div className="flex flex-col gap-2">
            <LemonLabel>Basic</LemonLabel>
            <LemonLabel info={'I am some extra info'}>Label with info</LemonLabel>
        </div>
    )
}

// export const Disabled = Template.bind({})
// Disabled.args = {
//     label: "You can't check this out",
//     disabled: true,
// }

// export const NoLabel = Template.bind({})
// NoLabel.args = {}

// export const Bordered = Template.bind({})
// Bordered.args = {
//     label: 'Look at my lovely border',
//     bordered: true,
// }
