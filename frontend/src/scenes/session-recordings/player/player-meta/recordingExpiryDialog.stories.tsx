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
        expiryTime: '2026-09-16T00:00:00.000000Z',
        exportsAvailable: true,
        exportDisabledReasons: {},
        onExportVideo: () => {},
        onExportJson: () => {},
    },
    parameters: {
        // The dialog counts the days from now to the expiry time, so the clock has to stand still
        // for the story to keep showing the same deadline.
        mockDate: '2026-09-12T12:00:00.000Z',
    },
}
export default meta

export const DaysLeft: Story = {}

export const ExpiresToday: Story = {
    args: { recordingTtlDays: 0, expiryTime: '2026-09-12T20:00:00.000000Z' },
}

export const VideoExportUnavailable: Story = {
    args: { exportDisabledReasons: { video: 'You have reached your export limit.' } },
}

export const SharedPlayerWithoutExports: Story = {
    args: { exportsAvailable: false },
}
