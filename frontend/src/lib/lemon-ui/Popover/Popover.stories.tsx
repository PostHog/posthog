import type { Meta, StoryObj } from '@storybook/react'

import { IconChevronDown } from '@posthog/icons'

import { Popover, PopoverProps } from './Popover'

type Story = StoryObj<PopoverProps>
const meta: Meta<PopoverProps> = {
    title: 'Lemon UI/Popover',
    component: Popover as any,
    tags: ['autodocs', 'test-skip'], // FIXME: This story needs a play test for the popup to show up in snapshots
}
export default meta

export const Popover_: Story = {
    args: {
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
    },
}
