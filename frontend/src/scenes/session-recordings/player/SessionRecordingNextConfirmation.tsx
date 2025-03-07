import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

export function SessionRecordingNextConfirmation(): JSX.Element {
    const { showingNextRecordingConfirmation, similarRecordingsCount } = useValues(sessionRecordingPlayerLogic)
    const { hideNextRecordingConfirmation, confirmNextRecording } = useActions(sessionRecordingPlayerLogic)

    return (
        <LemonModal
            isOpen={showingNextRecordingConfirmation}
            onClose={hideNextRecordingConfirmation}
            title="Mark similar recordings as viewed?"
            footer={
                <>
                    <LemonButton onClick={hideNextRecordingConfirmation} type="secondary">
                        No
                    </LemonButton>
                    <LemonButton onClick={confirmNextRecording} type="primary">
                        Yes
                    </LemonButton>
                </>
            }
        >
            <p>
                Would you like to mark <strong>{similarRecordingsCount}</strong> similar recordings as viewed?
            </p>
        </LemonModal>
    )
}
