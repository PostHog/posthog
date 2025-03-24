import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { LemonCheckbox, LemonCheckboxProps } from './LemonCheckbox'

type Story = StoryObj<typeof LemonCheckbox>
const meta: Meta<typeof LemonCheckbox> = {
    title: 'Lemon UI/Lemon Checkbox',
    component: LemonCheckbox,
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof LemonCheckbox> = (props: LemonCheckboxProps) => {
    return <LemonCheckbox {...props} />
}

export const Basic: Story = Template.bind({})
Basic.args = {
    label: 'Check this out',
}

export const Overview = (): JSX.Element => {
    return (
        <div className="deprecated-space-y-2">
            <LemonCheckbox label="Unchecked" />
            <LemonCheckbox label="Checked" checked />
            <LemonCheckbox label="Indeterminate" checked="indeterminate" />

            <LemonCheckbox label="Bordered Unchecked" bordered />
            <LemonCheckbox label="Bordered Checked" checked bordered />
            <LemonCheckbox label="Bordered Indeterminate" checked="indeterminate" bordered />

            <LemonCheckbox label="Bordered FullWidth" fullWidth bordered />
            <LemonCheckbox label="Bordered small" bordered size="small" />

            <div className="w-20">
                <LemonCheckbox label="Bordered with a really long label" bordered />
            </div>
        </div>
    )
}

export const Disabled: Story = Template.bind({})
Disabled.args = {
    label: "You can't check this out",
    disabled: true,
}

export const DisabledWithReason: Story = Template.bind({})
DisabledWithReason.args = {
    label: "You can't check this out",
    disabledReason: 'This is not the way to Amarillo',
}

export const NoLabel: Story = Template.bind({})
NoLabel.args = {}

export const Bordered: Story = Template.bind({})
Bordered.args = {
    label: 'A border makes for good visual separation if there is other content neighboring a checkbox. Probably not used as part of a form.',
    bordered: true,
}
