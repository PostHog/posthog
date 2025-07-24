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
        <>
            <ViewRecordingButton sessionId="123456789" type="secondary" />
            <ViewRecordingButton
                sessionId="123456789"
                type="secondary"
                minimumDuration={2000}
                recordingDuration={1000}
            />
        </>
    )
}
