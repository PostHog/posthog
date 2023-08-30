import { StoryFn, Meta, StoryObj } from '@storybook/react'

import { Popover } from './Popover'
import { IconArrowDropDown } from 'lib/lemon-ui/icons'

type Story = StoryObj<typeof Popover>
const meta: Meta<typeof Popover> = {
    title: 'Lemon UI/Popover',
    component: Popover,
    parameters: {
        testOptions: {
            skip: true, // FIXME: This story needs a play test for the popup to show up in snapshots
        },
    },
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof Popover> = (args) => <Popover {...args} />

export const Popover_: Story = Template.bind({})
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
