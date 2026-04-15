import { Meta, StoryObj } from '@storybook/react'

import { RecordingDeleted, RecordingDeletedProps } from './RecordingDeleted'

type Story = StoryObj<RecordingDeletedProps>
const meta: Meta<RecordingDeletedProps> = {
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
