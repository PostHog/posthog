import { useActions, useValues } from 'kea'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { SessionPlayerState } from '~/types'
import { IconErrorOutline, IconPlay } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import './PlayerFrameOverlay.scss'
import { PlayerUpNext } from './PlayerUpNext'
import { useState } from 'react'
import clsx from 'clsx'
import { getCurrentExporterData } from '~/exporter/exporterViewLogic'

const PlayerFrameOverlayContent = ({
    currentPlayerState,
}: {
    currentPlayerState: SessionPlayerState
}): JSX.Element | null => {
    let content = null
    const pausedState =
        currentPlayerState === SessionPlayerState.PAUSE || currentPlayerState === SessionPlayerState.READY
    const isInExportContext = !!getCurrentExporterData()

    if (currentPlayerState === SessionPlayerState.ERROR) {
        content = (
            <div className="flex flex-col justify-center items-center p-6 bg-bg-light rounded m-6 gap-2 max-w-120 shadow">
                <IconErrorOutline className="text-danger text-5xl" />
                <div className="font-bold text-default text-lg">We're unable to play this recording</div>
                <div className="text-muted text-sm text-center">
                    An error occurred that is preventing this recording from being played. You can refresh the page to
                    reload the recording.
                </div>
                <LemonButton
                    onClick={() => {
                        window.location.reload()
                    }}
                    type="primary"
                    fullWidth
                    center
                >
                    Reload
                </LemonButton>
                <LemonButton
                    targetBlank
                    to="https://posthog.com/support?utm_medium=in-product&utm_campaign=recording-not-found"
                    type="secondary"
                    fullWidth
                    center
                >
                    Contact support
                </LemonButton>
            </div>
        )
    }
    if (currentPlayerState === SessionPlayerState.BUFFER) {
        content = (
            <div className="SessionRecordingPlayer--buffering text-3xl italic font-medium text-white">Buffering…</div>
        )
    }
    if (pausedState) {
        content = <IconPlay className="text-6xl text-white" />
    }
    if (currentPlayerState === SessionPlayerState.SKIP) {
        content = <div className="text-3xl italic font-medium text-white">Skipping inactivity</div>
    }
    return content ? (
        <div
            className={clsx(
                'PlayerFrameOverlay__content',
                pausedState && !isInExportContext && 'PlayerFrameOverlay__content--only-hover'
            )}
            aria-busy={currentPlayerState === SessionPlayerState.BUFFER}
        >
            {content}
        </div>
    ) : null
}

export function PlayerFrameOverlay(): JSX.Element {
    const { currentPlayerState, playlistLogic } = useValues(sessionRecordingPlayerLogic)
    const { togglePlayPause } = useActions(sessionRecordingPlayerLogic)

    const [interrupted, setInterrupted] = useState(false)

    return (
        <div
            className="PlayerFrameOverlay"
            onClick={togglePlayPause}
            onMouseMove={() => setInterrupted(true)}
            onMouseOut={() => setInterrupted(false)}
        >
            <PlayerFrameOverlayContent currentPlayerState={currentPlayerState} />
            {playlistLogic ? (
                <PlayerUpNext
                    playlistLogic={playlistLogic}
                    interrupted={interrupted}
                    clearInterrupted={() => setInterrupted(false)}
                />
            ) : undefined}
        </div>
    )
}
