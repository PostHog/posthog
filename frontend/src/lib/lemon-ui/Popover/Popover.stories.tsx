import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { IconChevronDown } from '@posthog/icons'

import { Popover } from './Popover'

type Story = StoryObj<typeof Popover>
const meta: Meta<typeof Popover> = {
    title: 'Lemon UI/Popover',
    component: Popover,
    tags: ['autodocs', 'test-skip'], // FIXME: This story needs a play test for the popup to show up in snapshots
}
export default meta

const Template: StoryFn<typeof Popover> = (args) => <Popover {...args} />

export const Popover_: Story = Template.bind({})
Popover_.args = {
    visible: true,
    children: (
        <span className="text-2xl">
            <IconChevronDown />
        </span>
    ),
    overlay: (
        <>
            <h3>Surprise! 😱</h3>
            <span>You have been gnomed.</span>
        </>
    ),
}
