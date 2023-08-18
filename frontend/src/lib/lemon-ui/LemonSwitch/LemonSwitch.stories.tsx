import { useState } from 'react'
import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { LemonSwitch as RawLemonSwitch, LemonSwitchProps } from './LemonSwitch'
import { IconGlobeLock } from 'lib/lemon-ui/icons'

const LemonSwitch = ({ checked, ...props }: Partial<LemonSwitchProps>): JSX.Element => {
    const [isChecked, setIsChecked] = useState(checked || false)
    return <RawLemonSwitch {...props} checked={isChecked} onChange={setIsChecked} />
}

type Story = StoryObj<typeof RawLemonSwitch>
const meta: Meta<typeof LemonSwitch> = {
    title: 'Lemon UI/Lemon Switch',
    component: LemonSwitch,
    args: {
        label: 'Switch this!',
    },
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof RawLemonSwitch> = (props: LemonSwitchProps) => {
    return <LemonSwitch {...props} />
}

export const Basic: Story = {
    render: Template,
    args: {},
}

export const Overview = (): JSX.Element => {
    return (
        <div className="space-y-2">
            <LemonSwitch label="Unchecked" checked={false} />
            <LemonSwitch label="Checked" checked />

            <LemonSwitch label="Bordered Unchecked" bordered />
            <LemonSwitch label="Bordered Checked" checked bordered />

            <LemonSwitch label="Bordered FullWidth" fullWidth bordered />
            <LemonSwitch label="Bordered FullWidth icon" fullWidth bordered icon={<IconGlobeLock />} />
            <LemonSwitch label="Bordered disabled" bordered disabled />
        </div>
    )
}

export const Standalone: Story = {
    render: Template,
    args: { label: undefined },
}

export const Bordered: Story = {
    render: Template,
    args: { bordered: true },
}

export const Disabled: Story = {
    render: Template,
    args: { disabled: true },
}
