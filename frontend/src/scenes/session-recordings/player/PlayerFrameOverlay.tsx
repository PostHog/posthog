import './PlayerFrameOverlay.scss'

import { useActions, useValues } from 'kea'

import { IconEmoji, IconPlay, IconRewindPlay, IconWarning } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { cn } from 'lib/utils/css-classes'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { getCurrentExporterData } from '~/exporter/exporterViewLogic'
import { SessionPlayerState } from '~/types'

import { CommentOnRecordingButton } from './commenting/CommentOnRecordingButton'
import { ClipRecording } from './controller/ClipRecording'
import { Screenshot } from './controller/PlayerController'
import { playerSettingsLogic } from './playerSettingsLogic'
import { SessionRecordingPlayerMode } from './sessionRecordingPlayerLogic'

const PlayerFrameOverlayActions = (): JSX.Element | null => {
    const { setQuickEmojiIsOpen } = useActions(sessionRecordingPlayerLogic)
    const { quickEmojiIsOpen } = useValues(sessionRecordingPlayerLogic)

    return (
        <div className="flex gap-1 mt-4">
            <CommentOnRecordingButton className="text-2xl text-white" data-attr="replay-overlay-comment" />
            <LemonButton
                size="xsmall"
                icon={<IconEmoji className="text-2xl text-white" />}
                onClick={(e) => {
                    e.stopPropagation()
                    setQuickEmojiIsOpen(!quickEmojiIsOpen)
                }}
            />
            <Screenshot className="text-2xl text-white" data-attr="replay-overlay-screenshot" />
            <ClipRecording className="text-2xl text-white" data-attr="replay-overlay-clip" />
        </div>
    )
}

const PlayerFrameOverlayContent = (): JSX.Element | null => {
    const { currentPlayerState, endReached, logicProps } = useValues(sessionRecordingPlayerLogic)
    const { isCinemaMode } = useValues(playerSettingsLogic)

    let content = null
    const pausedState =
        currentPlayerState === SessionPlayerState.PAUSE || currentPlayerState === SessionPlayerState.READY
    const isInExportContext = !!getCurrentExporterData()
    const playerMode = logicProps.mode ?? SessionRecordingPlayerMode.Standard
    const showActionsOnOverlay = !isCinemaMode && playerMode === SessionRecordingPlayerMode.Standard && pausedState

    if (currentPlayerState === SessionPlayerState.ERROR) {
        content = (
            <div className="flex flex-col justify-center items-center p-6 bg-surface-primary rounded m-6 gap-2 max-w-120 shadow-sm">
                <IconWarning className="text-danger text-5xl" />
                <div className="font-bold text-text-3000 text-lg">We're unable to play this recording</div>
                <div className="text-secondary text-sm text-center">
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
            <div className="flex flex-col items-center justify-center">
                <IconPlay className="text-6xl text-white" />
                {showActionsOnOverlay && <PlayerFrameOverlayActions />}
            </div>
        )
    }
    if (currentPlayerState === SessionPlayerState.SKIP) {
        content = <div className="text-3xl italic font-medium text-white">Skipping inactivity</div>
    }
    return content ? (
        <div
            className={cn(
                'PlayerFrameOverlay__content absolute inset-0 z-1 flex items-center justify-center bg-black/15 transition-opacity duration-100',
                pausedState && !isInExportContext ? 'opacity-0 hover:opacity-100' : 'opacity-80 hover:opacity-100'
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
