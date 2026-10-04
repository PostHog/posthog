import type { Meta } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import ViewRecordingButton, { ViewRecordingButtonProps, ViewRecordingButtonVariant } from './ViewRecordingButton'

const meta = {
    title: 'UI/ViewRecordingButton',
    component: ViewRecordingButton,
    tags: ['autodocs'],
} satisfies Meta<ViewRecordingButtonProps>

export default meta

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

const batchCheckExists = (): [number, { results: Record<string, boolean> }] => [
    200,
    { results: { 'session-with-recording': true } },
]

export function CheckRecordingExists(): JSX.Element {
    return (
        <div className="flex flex-col gap-y-2 grow-0">
            <ViewRecordingButton
                sessionId="session-with-recording"
                variant={ViewRecordingButtonVariant.Link}
                checkRecordingExists
            />
            <ViewRecordingButton
                sessionId="session-without-recording"
                variant={ViewRecordingButtonVariant.Link}
                timestamp="2024-01-01T00:00:00Z"
                checkRecordingExists
            />
            <ViewRecordingButton
                sessionId="session-without-recording"
                type="secondary"
                size="xsmall"
                checkRecordingExists
            />
        </div>
    )
}
CheckRecordingExists.decorators = [
    mswDecorator({
        post: {
            '/api/environments/:id/session_recordings/batch_check_exists': batchCheckExists,
            '/api/projects/:id/session_recordings/batch_check_exists': batchCheckExists,
        },
    }),
]
