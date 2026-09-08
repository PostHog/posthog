import { Meta, StoryObj } from '@storybook/react'

import { LemonDialog } from '@posthog/lemon-ui'

import {
    RecordingExpiryDialogProps,
    recordingExpiryDialogProps,
} from 'scenes/session-recordings/player/player-meta/recordingExpiryDialog'

function RecordingExpiryDialog(props: RecordingExpiryDialogProps): JSX.Element {
    return (
        <div className="min-h-100 flex items-start">
            <LemonDialog {...recordingExpiryDialogProps(props)} inline />
        </div>
    )
}

type Story = StoryObj<typeof RecordingExpiryDialog>
const meta: Meta<typeof RecordingExpiryDialog> = {
    title: 'Replay/Player/RecordingExpiryDialog',
    component: RecordingExpiryDialog,
    args: {
        recordingTtlDays: 4,
        expiryTime: '2023-06-01T00:00:00.000000Z',
        exportsAvailable: true,
        exportDisabledReasons: {},
        onExportVideo: () => {},
        onExportJson: () => {},
    },
}
export default meta

export const DaysLeft: Story = {}

export const ExpiresToday: Story = {
    args: { recordingTtlDays: 0 },
}

export const VideoExportUnavailable: Story = {
    args: { exportDisabledReasons: { video: 'You have reached your export limit.' } },
}

export const SharedPlayerWithoutExports: Story = {
    args: { exportsAvailable: false },
}
