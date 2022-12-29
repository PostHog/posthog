import { ComponentMeta, ComponentStory } from '@storybook/react'

import { Trace } from 'lib/components/Performance/Traces/Trace'

export default {
    title: 'Components/Performance/Traces',
    component: Trace,
    parameters: { chromatic: { disableSnapshot: false } },
    argTypes: {
        // label: {
        //     defaultValue: 'Switch this!',
        // },
    },
} as ComponentMeta<typeof Trace>

const Template: ComponentStory<typeof Trace> = () => {
    return <Trace />
}

export const Basic = Template.bind({})
Basic.args = {}

// export const Overview = (): JSX.Element => {
//     return (
//         <div className="space-y-2">
//             <LemonSwitch label="Unchecked" checked={false} />
//             <LemonSwitch label="Checked" checked />
//
//             <LemonSwitch label="Bordered Unchecked" bordered />
//             <LemonSwitch label="Bordered Checked" checked bordered />
//
//             <LemonSwitch label="Bordered FullWidth" fullWidth bordered />
//             <LemonSwitch label="Bordered FullWidth icon" fullWidth bordered icon={<IconGlobeLock />} />
//             <LemonSwitch label="Bordered disabled" bordered disabled />
//             <LemonSwitch label="Bordered small" bordered size="small" />
//         </div>
//     )
// }
//
// export const Standalone = Template.bind({})
// Standalone.args = { label: undefined }
//
// export const Bordered = Template.bind({})
// Bordered.args = { bordered: true }
//
// export const Disabled = Template.bind({})
// Disabled.args = { disabled: true }
