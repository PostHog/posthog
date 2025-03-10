import { LemonButton, LemonDivider, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import ViewRecordingButton from 'lib/components/ViewRecordingButton/ViewRecordingButton'

import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

export function SessionRecordingNextConfirmation(): JSX.Element {
    const { showingNextRecordingConfirmation, similarRecordingsCount, similarRecordings } =
        useValues(sessionRecordingPlayerLogic)
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
            <>
                <p>
                    Would you like to mark <strong>{similarRecordingsCount}</strong> similar recordings as viewed?
                </p>
                <ul className="deprecated-space-y-px">
                    {similarRecordings.map((recording, i) => (
                        <>
                            {i > 0 && <LemonDivider className="my-0" />}
                            <li>
                                <ViewRecordingButton
                                    sessionId={recording.id as string}
                                    label={`View recording ${i + 1}`}
                                    checkIfViewed={true}
                                    inModal={true}
                                    fullWidth={true}
                                />
                            </li>
                        </>
                    ))}
                </ul>
            </>
        </LemonModal>
    )
}
