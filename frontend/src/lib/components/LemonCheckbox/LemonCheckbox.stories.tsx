import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonCheckbox, LemonCheckboxProps } from './LemonCheckbox'

export default {
    title: 'Lemon UI/Lemon Checkbox',
    component: LemonCheckbox,
} as ComponentMeta<typeof LemonCheckbox>

const Template: ComponentStory<typeof LemonCheckbox> = (props: LemonCheckboxProps) => {
    return <LemonCheckbox {...props} />
}

export const Basic = Template.bind({})
Basic.args = {
    label: 'Check this out',
}

export const Overview = (): JSX.Element => {
    return (
        <div className="space-y-2">
            <LemonCheckbox label="Unchecked" />
            <LemonCheckbox label="Checked" checked />
            <LemonCheckbox label="Indeterminate" checked="indeterminate" />

            <LemonCheckbox label="Bordered Unchecked" bordered />
            <LemonCheckbox label="Bordered Checked" checked bordered />
            <LemonCheckbox label="Bordered Indeterminate" checked="indeterminate" bordered />

            <LemonCheckbox label="Bordered FullWidth" fullWidth bordered />
            <LemonCheckbox label="Bordered small" bordered size="small" />
        </div>
    )
}

export const Disabled = Template.bind({})
Disabled.args = {
    label: "You can't check this out",
    disabled: true,
}

export const NoLabel = Template.bind({})
NoLabel.args = {}

export const Bordered = Template.bind({})
Bordered.args = {
    label: 'Look at my lovely border',
    bordered: true,
}
