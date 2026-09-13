import type { Meta } from '@storybook/react'

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

export function RecordingStatuses(): JSX.Element {
    return (
        <div className="flex flex-col gap-y-2 grow-0">
            {[
                'active',
                'buffering',
                'lazy_loading',
                'awaiting_config',
                'paused',
                'disabled',
                'missing_config',
                'rrweb_error',
            ].map((recordingStatus) => (
                <ViewRecordingButton
                    key={recordingStatus}
                    fullWidth
                    type="secondary"
                    sessionId="123456789"
                    recordingStatus={recordingStatus}
                    label={recordingStatus}
                />
            ))}
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
