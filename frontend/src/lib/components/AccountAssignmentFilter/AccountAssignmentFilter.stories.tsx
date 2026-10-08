import type { Meta, StoryObj } from '@storybook/react'

import { AccountAssignmentFilter } from './AccountAssignmentFilter'

const meta = {
    title: 'Components/Account assignment filter',
    component: AccountAssignmentFilter,
    args: {
        assignedToUserIds: [],
        onAssignedToUserIdsChange: () => {},
        onStatusChange: () => {},
    },
} satisfies Meta<typeof AccountAssignmentFilter>

export default meta

type Story = StoryObj<typeof meta>

export const AllAccounts: Story = {
    args: { status: 'all' },
}

export const AssignedToAnyone: Story = {
    args: { status: 'assigned' },
}

export const AssignedToPeople: Story = {
    args: { status: 'assigned', assignedToUserIds: [1, 2] },
}

export const UnassignedOnly: Story = {
    args: { status: 'unassigned' },
}
