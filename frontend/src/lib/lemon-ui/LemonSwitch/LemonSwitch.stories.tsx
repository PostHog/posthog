import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { LemonSwitchProps, LemonSwitch as RawLemonSwitch } from './LemonSwitch'

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

export const Basic: Story = Template.bind({})
Basic.args = {}

export const Overview = (): JSX.Element => {
    return (
        <div className="deprecated-space-y-2">
            <LemonSwitch label="Unchecked" checked={false} />
            <LemonSwitch label="Checked" checked />

            <LemonSwitch label="Bordered Unchecked" bordered />
            <LemonSwitch label="Bordered Checked" checked bordered />

            <LemonSwitch label="Bordered FullWidth" fullWidth bordered />
            <LemonSwitch label="Bordered disabled" bordered disabled />

            <div className="w-20">
                <LemonSwitch label="Bordered with a really long label" bordered />
            </div>
            <div className="w-20">
                <LemonSwitch label="extra extra small" size="xxsmall" bordered />
            </div>
            <div className="w-20">
                <LemonSwitch label="extra small" size="xsmall" bordered />
            </div>
            <div className="w-20">
                <LemonSwitch label="small" size="small" bordered />
            </div>
            <div className="w-20">
                <LemonSwitch label="medium (default)" size="medium" bordered />
            </div>
        </div>
    )
}

export const Standalone: Story = Template.bind({})
Standalone.args = { label: undefined }

export const Bordered: Story = Template.bind({})
Bordered.args = { bordered: true }

export const Disabled: Story = Template.bind({})
Disabled.args = { disabled: true }

const SwitchCell = (props: Partial<LemonSwitchProps>): JSX.Element => {
    return (
        <td className="border border-bg-3000 border-4 p-2">
            <LemonSwitch label={props.size} {...props} />
        </td>
    )
}

export const Sizes = (): JSX.Element => {
    return (
        <table className="table-auto border-collapse border-bg-3000 border-4">
            <tbody>
                <tr>
                    <SwitchCell size="xxsmall" bordered={false} />
                    <SwitchCell size="xsmall" bordered={false} />
                    <SwitchCell size="small" bordered={false} />
                    <SwitchCell size="medium" bordered={false} />
                </tr>
                <tr>
                    <SwitchCell size="xxsmall" bordered={true} />
                    <SwitchCell size="xsmall" bordered={true} />
                    <SwitchCell size="small" bordered={true} />
                    <SwitchCell size="medium" bordered={true} />
                </tr>
            </tbody>
        </table>
    )
}

export const SizesLoading = (): JSX.Element => {
    return (
        <table className="table-auto border-collapse border-bg-3000 border-4">
            <tbody>
                <tr>
                    <SwitchCell size="xxsmall" checked={false} loading={true} />
                    <SwitchCell size="xsmall" checked={false} loading={true} />
                    <SwitchCell size="small" checked={false} loading={true} />
                    <SwitchCell size="medium" checked={false} loading={true} />
                </tr>
                <tr>
                    <SwitchCell size="xxsmall" checked={true} loading={true} />
                    <SwitchCell size="xsmall" checked={true} loading={true} />
                    <SwitchCell size="small" checked={true} loading={true} />
                    <SwitchCell size="medium" checked={true} loading={true} />
                </tr>
            </tbody>
        </table>
    )
}
SizesLoading.parameters = { testOptions: { waitForLoadersToDisappear: false } }

export const WithAccessControl = (): JSX.Element => {
    return (
        <div className="deprecated-space-y-2">
            <LemonSwitch
                label="Enabled (admin ≥ admin)"
                checked={true}
                onChange={() => {}}
                accessControl={{
                    userLevel: AccessControlLevel.Admin,
                    minLevel: AccessControlLevel.Admin,
                    resource: AccessControlResourceType.Project,
                }}
            />
            <LemonSwitch
                label="Disabled (viewer < admin)"
                checked={false}
                onChange={() => {}}
                accessControl={{
                    userLevel: AccessControlLevel.Viewer,
                    minLevel: AccessControlLevel.Admin,
                    resource: AccessControlResourceType.Project,
                }}
            />
        </div>
    )
}
