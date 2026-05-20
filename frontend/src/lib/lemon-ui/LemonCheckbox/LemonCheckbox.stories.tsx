import type { Meta, StoryObj } from '@storybook/react'

import { LemonCheckbox, LemonCheckboxProps } from './LemonCheckbox'

type Story = StoryObj<LemonCheckboxProps>
const meta: Meta<LemonCheckboxProps> = {
    title: 'Lemon UI/Lemon Checkbox',
    component: LemonCheckbox,
    tags: ['autodocs'],
}
export default meta

export const Basic: Story = {
    args: {
        label: 'Check this out',
    },
}

export const Overview: Story = {
    render: () => {
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
    },
}

export const Disabled: Story = {
    args: {
        label: "You can't check this out",
        disabled: true,
    },
}

export const DisabledWithReason: Story = {
    args: {
        label: "You can't check this out",
        disabledReason: 'This is not the way to Amarillo',
    },
}

export const NoLabel: Story = {
    args: {},
}

export const Bordered: Story = {
    args: {
        label: 'A border makes for good visual separation if there is other content neighboring a checkbox. Probably not used as part of a form.',
        bordered: true,
    },
}
