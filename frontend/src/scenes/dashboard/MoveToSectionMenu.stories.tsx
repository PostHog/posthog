import type { Meta, StoryObj } from '@storybook/react'

import { MoveToSectionMenu } from './MoveToSectionMenu'

const meta: Meta<typeof MoveToSectionMenu> = {
    title: 'Scenes/Dashboard/Move To Section Menu',
    component: MoveToSectionMenu,
    args: {
        destinations: [
            { groupId: 'a', label: 'Acquisition' },
            { groupId: 'b', label: 'Untitled section' },
        ],
        onMove: () => {},
    },
}
export default meta

type Story = StoryObj<typeof MoveToSectionMenu>

export const Default: Story = {}

export const HiddenWhenEmpty: Story = {
    args: { destinations: [] },
}
