import { QuillIngestionControlsSummary } from 'lib/components/IngestionControls/QuillIngestionControlsSummary'
import { Trigger } from 'lib/components/IngestionControls/types'

import { QuillRecordingDisabledBanner } from './QuillRecordingDisabledBanner'

export function QuillRecordingTriggersSummary({
    recordingEnabled,
    triggers,
}: {
    recordingEnabled: boolean
    triggers: Trigger[]
}): JSX.Element {
    if (!recordingEnabled) {
        return <QuillRecordingDisabledBanner />
    }

    return (
        <QuillIngestionControlsSummary
            triggers={triggers}
            controlDescription="sessions recorded"
            docsLink={{
                to: 'https://posthog.com/docs/session-replay/how-to-control-which-sessions-you-record',
                label: 'Read about how to start and stop sessions in our docs.',
            }}
        />
    )
}
