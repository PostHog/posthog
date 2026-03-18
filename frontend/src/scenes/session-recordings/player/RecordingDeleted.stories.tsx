import { Meta, StoryObj } from '@storybook/react'

import { RecordingDeleted } from './RecordingDeleted'

type Story = StoryObj<typeof RecordingDeleted>
const meta: Meta<typeof RecordingDeleted> = {
    title: 'Replay/Player/RecordingDeleted',
    component: RecordingDeleted,
}
export default meta

export const WithTimestamp: Story = {
    args: {
        deletedAt: 1700000000,
    },
}

export const WithoutTimestamp: Story = {
    args: {
        deletedAt: null,
    },
}
