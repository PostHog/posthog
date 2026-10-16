import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import ViewRecordingButton, { ViewRecordingButtonProps, ViewRecordingButtonVariant } from './ViewRecordingButton'

const meta = {
    title: 'UI/ViewRecordingButton',
    component: ViewRecordingButton,
    tags: ['autodocs'],
} satisfies Meta<ViewRecordingButtonProps>

export default meta

type Story = StoryObj<typeof meta>

export const EarlyEventWithLaterRecording: Story = {
    args: { sessionId: '01900000-0000-7000-8000-000000000001', recordingStatus: 'disabled', hasRecording: false },
    decorators: [
        mswDecorator({
            post: {
                '/api/projects/:team/session_recordings/batch_check_exists': {
                    results: { '01900000-0000-7000-8000-000000000001': true },
                },
            },
        }),
    ],
    parameters: {
        featureFlags: { [FEATURE_FLAGS.REPLAY_EVENT_RECORDING_AVAILABILITY]: 'session_lookup' },
        testOptions: { waitForSelector: '[aria-disabled="false"]' },
    },
}

export function Default(): JSX.Element {
    return (
        <div className="flex flex-col gap-y-2 grow-0">
            <ViewRecordingButton fullWidth sessionId="123456789" type="secondary" />
            <ViewRecordingButton fullWidth sessionId="123456789" type="secondary" recordingStatus="disabled" />
            <ViewRecordingButton
                sessionId="123456789"
                type="secondary"
                fullWidth
                minimumDuration={2000}
                recordingDuration={1000}
            />
        </div>
    )
}

export function LinkVariant(): JSX.Element {
    return (
        <div className="flex flex-col gap-y-2 grow-0">
            <ViewRecordingButton sessionId="123456789" variant={ViewRecordingButtonVariant.Link} />
            <ViewRecordingButton
                sessionId="123456789"
                variant={ViewRecordingButtonVariant.Link}
                label="abc123-session-id"
            />
            <ViewRecordingButton
                sessionId="123456789"
                variant={ViewRecordingButtonVariant.Link}
                minimumDuration={2000}
                recordingDuration={1000}
            />
            <ViewRecordingButton sessionId={undefined} variant={ViewRecordingButtonVariant.Link} />
        </div>
    )
}
