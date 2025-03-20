import { LemonButton, LemonDivider, LemonModal } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import ViewRecordingButton from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { Fragment } from 'react'

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
                <div className="overflow-y-auto max-h-80 border rounded">
                    <ul className="deprecated-space-y-px m-0">
                        {similarRecordings.map((recording, i) => (
                            <Fragment key={recording}>
                                {i > 0 && <LemonDivider className="my-0" />}
                                <li>
                                    <ViewRecordingButton
                                        sessionId={recording}
                                        label={`View recording ${i + 1}`}
                                        checkIfViewed={true}
                                        inModal={true}
                                        fullWidth={true}
                                    />
                                </li>
                            </Fragment>
                        ))}
                    </ul>
                </div>
            </>
        </LemonModal>
    )
}
