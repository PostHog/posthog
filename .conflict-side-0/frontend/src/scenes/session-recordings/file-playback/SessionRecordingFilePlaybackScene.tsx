import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { IconUploadFile } from 'lib/lemon-ui/icons'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

import { SessionRecordingPlayer } from '../player/SessionRecordingPlayer'
import { sessionRecordingFilePlaybackSceneLogic } from './sessionRecordingFilePlaybackSceneLogic'

export const scene: SceneExport = {
    component: SessionRecordingFilePlaybackScene,
    logic: sessionRecordingFilePlaybackSceneLogic,
    settingSectionId: 'environment-replay',
}

export function SessionRecordingFilePlaybackScene(): JSX.Element {
    const { loadFromFile, resetSessionRecording } = useActions(sessionRecordingFilePlaybackSceneLogic)
    const { sessionRecording, sessionRecordingLoading, playerProps } = useValues(sessionRecordingFilePlaybackSceneLogic)
    const { hasAvailableFeature } = useValues(userLogic)
    const filePlaybackEnabled = hasAvailableFeature(AvailableFeature.RECORDINGS_FILE_EXPORT)

    const dropRef = useRef<HTMLDivElement>(null)

    if (!filePlaybackEnabled) {
        return (
            <PayGateMini
                feature={AvailableFeature.RECORDINGS_FILE_EXPORT}
                className="py-8"
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
                    <SessionRecordingPlayer {...playerProps} />
                </div>
            ) : (
                <div
                    ref={dropRef}
                    className="w-full border rounded p-20 text-secondary flex flex-col items-center justify-center"
                >
                    <LemonFileInput
                        accept="application/json"
                        multiple={false}
                        onChange={(files) => loadFromFile(files[0])}
                        alternativeDropTargetRef={dropRef}
                        callToAction={
                            <div className="flex flex-col items-center justify-center deprecated-space-y-2">
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
