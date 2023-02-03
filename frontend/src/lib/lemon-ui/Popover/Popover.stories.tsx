import { ComponentStory, ComponentMeta } from '@storybook/react'

import { Popover } from './Popover'
import { IconArrowDropDown } from 'lib/lemon-ui/icons'

export default {
    title: 'Lemon UI/Popover',
    component: Popover,
    parameters: {
        chromatic: {
            disableSnapshot: true, // FIXME: This story needs a play test for the popover to show up in snapshots
        },
    },
} as ComponentMeta<typeof Popover>

const Template: ComponentStory<typeof Popover> = (args) => <Popover {...args} />

export const Popover_ = Template.bind({})
Popover_.args = {
    visible: true,
    children: (
        <span className="text-2xl">
            <IconArrowDropDown />
        </span>
    ),
    overlay: (
        <>
            <h3>Surprise! 😱</h3>
            <span>You have been gnomed.</span>
        </>
    ),
}
