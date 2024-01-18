import { useActions, useValues } from 'kea'
import { PayGatePage } from 'lib/components/PayGatePage/PayGatePage'
import { IconUploadFile } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { useRef } from 'react'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import { SessionRecordingPlayer } from '../player/SessionRecordingPlayer'
import { sessionRecordingFilePlaybackLogic } from './sessionRecordingFilePlaybackLogic'

export function SessionRecordingFilePlayback(): JSX.Element {
    const { loadFromFile, resetSessionRecording } = useActions(sessionRecordingFilePlaybackLogic)
    const { sessionRecording, sessionRecordingLoading, playerKey } = useValues(sessionRecordingFilePlaybackLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const filePlaybackEnabled = hasAvailableFeature(AvailableFeature.RECORDINGS_FILE_EXPORT)

    const dropRef = useRef<HTMLDivElement>(null)

    if (!filePlaybackEnabled) {
        return (
            <PayGatePage
                featureKey={AvailableFeature.RECORDINGS_FILE_EXPORT}
                featureName="Recording Exports"
                header={
                    <>
                        Export and playback <span className="highlight">Recordings from file</span>!
                    </>
                }
                caption="Store your recordings outside of PostHog wherever you like."
                docsLink="https://posthog.com/docs/user-guides/session-recordings"
            />
        )
    }

    return (
        <div>
            {sessionRecordingLoading ? (
                <SpinnerOverlay />
            ) : sessionRecording ? (
                <div className="flex flex-col gap-2 h-screen pb-4">
                    <LemonBanner
                        type="info"
                        action={{
                            onClick: () => resetSessionRecording(),
                            children: 'Load a different recording',
                        }}
                    >
                        You are viewing a recording loaded from a file.
                    </LemonBanner>
                    <SessionRecordingPlayer sessionRecordingId="" playerKey={playerKey} />
                </div>
            ) : (
                <div
                    ref={dropRef}
                    className="w-full border rounded p-20 text-muted-alt flex flex-col items-center justify-center"
                >
                    <LemonFileInput
                        accept="application/json"
                        multiple={false}
                        onChange={(files) => loadFromFile(files[0])}
                        alternativeDropTargetRef={dropRef}
                        callToAction={
                            <div className="flex flex-col items-center justify-center space-y-2">
                                <span className="flex items-center gap-2 font-semibold">
                                    <IconUploadFile className="text-2xl" /> Load recording
                                </span>
                                <div>Drag and drop your exported recording here or click to open the file browser.</div>
                            </div>
                        }
                    />
                </div>
            )}
        </div>
    )
}
