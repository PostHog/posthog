import './PlayerFrameOverlay.scss'

import { IconPlay, IconRewindPlay, IconWarning } from '@posthog/icons'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { getCurrentExporterData } from '~/exporter/exporterViewLogic'
import { SessionPlayerState } from '~/types'

const PlayerFrameOverlayContent = (): JSX.Element | null => {
    const { currentPlayerState, endReached } = useValues(sessionRecordingPlayerLogic)
    let content = null
    const pausedState =
        currentPlayerState === SessionPlayerState.PAUSE || currentPlayerState === SessionPlayerState.READY
    const isInExportContext = !!getCurrentExporterData()

    if (currentPlayerState === SessionPlayerState.ERROR) {
        content = (
            <div className="flex flex-col justify-center items-center p-6 bg-card rounded m-6 gap-2 max-w-120 shadow-sm">
                <IconWarning className="text-danger text-5xl" />
                <div className="font-bold text-text-foreground text-lg">We're unable to play this recording</div>
                <div className="text-secondary-foreground text-sm text-center">
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
        content = endReached ? (
            <IconRewindPlay className="text-6xl text-white" />
        ) : (
            <IconPlay className="text-6xl text-white" />
        )
    }
    if (currentPlayerState === SessionPlayerState.SKIP) {
        content = <div className="text-3xl italic font-medium text-white">Skipping inactivity</div>
    }
    return content ? (
        <div
            className={clsx(
                'PlayerFrameOverlay__content absolute inset-0 z-1 flex items-center justify-center bg-black/15 opacity-80 transition-opacity duration-100 hover:opacity-100',
                pausedState && !isInExportContext && 'PlayerFrameOverlay__content--only-hover'
            )}
            aria-busy={currentPlayerState === SessionPlayerState.BUFFER}
        >
            {content}
        </div>
    ) : null
}

export function PlayerFrameOverlay(): JSX.Element {
    const { togglePlayPause } = useActions(sessionRecordingPlayerLogic)

    return (
        <div className="PlayerFrameOverlay absolute inset-0 z-10" onClick={togglePlayPause}>
            <PlayerFrameOverlayContent />
        </div>
    )
}
