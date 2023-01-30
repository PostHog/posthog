import { useState } from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'

import { LemonSwitch as RawLemonSwitch, LemonSwitchProps } from './LemonSwitch'
import { IconGlobeLock } from 'lib/lemon-ui/icons'

export default {
    title: 'Lemon UI/Lemon Switch',
    component: RawLemonSwitch,
    argTypes: {
        label: {
            defaultValue: 'Switch this!',
        },
    },
} as ComponentMeta<typeof LemonSwitch>

const LemonSwitch = ({ checked, ...props }: Partial<LemonSwitchProps>): JSX.Element => {
    const [isChecked, setIsChecked] = useState(checked || false)
    return <RawLemonSwitch {...props} checked={isChecked} onChange={setIsChecked} />
}

const Template: ComponentStory<typeof RawLemonSwitch> = (props: LemonSwitchProps) => {
    return <LemonSwitch {...props} />
}

export const Basic = Template.bind({})
Basic.args = {}

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
            <LemonSwitch label="Bordered small" bordered size="small" />
        </div>
    )
}

export const Standalone = Template.bind({})
Standalone.args = { label: undefined }

export const Bordered = Template.bind({})
Bordered.args = { bordered: true }

export const Disabled = Template.bind({})
Disabled.args = { disabled: true }
