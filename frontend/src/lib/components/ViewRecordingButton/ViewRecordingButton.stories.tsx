import type { Meta } from '@storybook/react'

import ViewRecordingButton from './ViewRecordingButton'

const meta = {
    title: 'UI/ViewRecordingButton',
    component: ViewRecordingButton,
    tags: ['autodocs'],
} satisfies Meta<typeof ViewRecordingButton>

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
