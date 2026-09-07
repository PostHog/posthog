import './PlayerFrameOverlay.scss'

import { useActions, useValues } from 'kea'
import { MouseEvent } from 'react'

import { IconEmoji, IconPlay, IconRewindPlay, IconWarning } from '@posthog/icons'

import { IconSkipBackward } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { cn } from 'lib/utils/css-classes'
import { humanizeBytes } from 'lib/utils/numbers'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { urls } from 'scenes/urls'

import { getCurrentExporterData } from '~/exporter/exporterViewLogic'
import { SessionPlayerState } from '~/types'

import { CommentOnRecordingButton } from './commenting/CommentOnRecordingButton'
import { ClipRecording } from './controller/ClipRecording'
import { Screenshot } from './controller/PlayerController'
import { SessionRecordingPlayerMode } from './sessionRecordingPlayerLogic'

const SeekIndicator = (): JSX.Element | null => {
    const { seekIndicator } = useValues(sessionRecordingPlayerLogic)

    if (!seekIndicator) {
        return null
    }

    const isForward = seekIndicator.direction === 'forward'

    return (
        <div
            className={cn(
                'SeekIndicator absolute inset-0 z-20 flex items-center pointer-events-none',
                isForward ? 'justify-end pr-[15%]' : 'justify-start pl-[15%]'
            )}
            key={`seek-indicator-${isForward ? 'forward' : 'backward'}-${Date.now()}`}
        >
            <div className="SeekIndicator__bubble flex flex-col items-center justify-center rounded-full bg-black/60 w-20 h-20">
                <IconSkipBackward
                    className={cn('SeekIndicator__icon text-white text-4xl', {
                        'SeekIndicator__icon--forward': isForward,
                    })}
                />
                <span className="text-white text-sm font-semibold">{seekIndicator.seconds}s</span>
            </div>
        </div>
    )
}

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

// Failures that a fresh load attempt can fix (a snapshot API or blob fetch that failed in transit),
// as opposed to a recording whose data is genuinely unplayable. Terminal responses from the
// snapshots API get their own player error, so they never land here and never offer a retry.
const RECOVERABLE_SNAPSHOT_ERRORS = [
    'loadSnapshotsForSourceFailure',
    'loadSnapshotSourcesFailure',
    'snapshotSourceLoadExhausted',
]

interface PlayerErrorCopy {
    title: string
    description: string
}

// Terminal responses from the snapshots API. Neither a retry nor a page reload brings the data back,
// so the overlay offers neither.
const PERMANENT_SNAPSHOT_ERROR_COPY: Record<string, PlayerErrorCopy> = {
    snapshotUnauthorized: {
        title: "We're unable to play this recording",
        description: 'Your session has expired. Sign in again to keep watching this recording.',
    },
    snapshotForbidden: {
        title: "We're unable to play this recording",
        description: "You don't have access to this recording. Ask an admin of this project for access.",
    },
    recordingNotFound: {
        title: 'This recording is no longer available',
        description:
            'PostHog has no data for this recording. It has passed the retention period for your project, or it never finished uploading.',
    },
    recordingDeleted: {
        title: 'This recording was deleted',
        description: 'Someone permanently deleted this recording, so there is nothing left to play.',
    },
}

// After this many retries the person has enough evidence that retrying does not work.
const MAX_OFFERED_SNAPSHOT_RETRIES = 2

function playerErrorCopy(playerError: string | null, retryCount: number): PlayerErrorCopy {
    if (playerError && playerError in PERMANENT_SNAPSHOT_ERROR_COPY) {
        return PERMANENT_SNAPSHOT_ERROR_COPY[playerError]
    }
    if (playerError === 'noPlayableFullSnapshot') {
        return {
            title: "We're unable to play this recording",
            description:
                'This part of the recording is missing the snapshot data needed to render it. The data never reached PostHog, usually because the browser was closed or went offline before the recording finished uploading.',
        }
    }
    if (playerError && RECOVERABLE_SNAPSHOT_ERRORS.includes(playerError)) {
        return {
            title: "We couldn't load this recording",
            description:
                retryCount >= MAX_OFFERED_SNAPSHOT_RETRIES
                    ? "Retrying hasn't helped. Contact support and we'll look into this recording."
                    : "We couldn't fetch the recording data. This is usually a temporary network problem. Retry, and if it keeps failing contact support.",
        }
    }
    return {
        title: "We're unable to play this recording",
        description:
            'An error occurred that is preventing this recording from being played. You can refresh the page to reload the recording.',
    }
}

const PlayerFrameOverlayContent = (): JSX.Element | null => {
    const {
        currentPlayerState,
        endReached,
        logicProps,
        playerError,
        isWaitingForIngestion,
        sessionPlayerMetaData,
        snapshotRetryCount,
    } = useValues(sessionRecordingPlayerLogic)
    const { setPlay, retryLoadingSnapshots } = useActions(sessionRecordingPlayerLogic)

    const handlePlay = (e: MouseEvent): void => {
        e.stopPropagation()
        setPlay()
    }

    let content = null
    const pausedState =
        currentPlayerState === SessionPlayerState.PAUSE || currentPlayerState === SessionPlayerState.READY
    const isInExportContext = !!getCurrentExporterData()
    const playerMode = logicProps.mode ?? SessionRecordingPlayerMode.Standard
    const showActionsOnOverlay = playerMode === SessionRecordingPlayerMode.Standard && pausedState

    if (currentPlayerState === SessionPlayerState.ERROR && playerError === 'recordingTooLarge') {
        const totalSize = sessionPlayerMetaData?.total_size
        content = (
            <div className="flex flex-col justify-center items-center p-6 bg-surface-primary rounded m-6 gap-2 max-w-120 shadow-sm">
                <IconWarning className="text-danger text-5xl" />
                <div className="font-bold text-text-3000 text-lg">We're unable to play this recording</div>
                <div className="text-secondary text-sm text-center">
                    It contains {totalSize ? `${humanizeBytes(totalSize)} of` : 'too much'} snapshot data in very large
                    chunks, more than the player can render. This usually comes from pages with rapidly changing
                    content. You can exclude those elements from capture to keep future recordings playable.
                </div>
                <LemonButton
                    targetBlank
                    to="https://posthog.com/docs/session-replay/privacy"
                    type="primary"
                    fullWidth
                    center
                >
                    Learn how to exclude elements
                </LemonButton>
            </div>
        )
    } else if (currentPlayerState === SessionPlayerState.ERROR) {
        const isMissingFullSnapshot = playerError === 'noPlayableFullSnapshot'
        const isUnauthorized = playerError === 'snapshotUnauthorized'
        const isRecoverable = !!playerError && RECOVERABLE_SNAPSHOT_ERRORS.includes(playerError)
        const isPermanent = !!playerError && playerError in PERMANENT_SNAPSHOT_ERROR_COPY
        const canRetry = isRecoverable && snapshotRetryCount < MAX_OFFERED_SNAPSHOT_RETRIES
        const { title, description } = playerErrorCopy(playerError, snapshotRetryCount)
        content = (
            <div className="flex flex-col justify-center items-center p-6 bg-surface-primary rounded m-6 gap-2 max-w-120 shadow-sm">
                <IconWarning className="text-danger text-5xl" />
                <div className="font-bold text-text-3000 text-lg">{title}</div>
                <div className="text-secondary text-sm text-center">{description}</div>
                {isUnauthorized && (
                    <LemonButton to={urls.login()} type="primary" fullWidth center>
                        Sign in
                    </LemonButton>
                )}
                {canRetry && (
                    <LemonButton
                        onClick={(e) => {
                            e.stopPropagation()
                            retryLoadingSnapshots()
                        }}
                        type="primary"
                        fullWidth
                        center
                    >
                        Retry
                    </LemonButton>
                )}
                {!isMissingFullSnapshot && !isPermanent && !isRecoverable && (
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
                )}
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
        content = isWaitingForIngestion ? (
            <div className="SessionRecordingPlayer--buffering flex flex-col items-center gap-1 text-center text-white">
                <div className="text-3xl italic font-medium">Still processing…</div>
                <div className="text-sm max-w-100">
                    This recording is finishing ingestion. It's usually ready to play within a few minutes.
                </div>
            </div>
        ) : (
            <div className="SessionRecordingPlayer--buffering text-3xl italic font-medium text-white">Buffering…</div>
        )
    }
    if (pausedState) {
        content = endReached ? (
            <LemonButton
                icon={<IconRewindPlay className="text-6xl text-white" />}
                aria-label="Rewind recording"
                data-attr="replay-overlay-rewind"
                onClick={handlePlay}
            />
        ) : (
            <div className="flex flex-col items-center justify-center">
                <LemonButton
                    icon={<IconPlay className="text-6xl text-white" />}
                    aria-label="Resume recording"
                    data-attr="replay-overlay-resume"
                    onClick={handlePlay}
                />
                {showActionsOnOverlay && <PlayerFrameOverlayActions />}
            </div>
        )
    }
    if (currentPlayerState === SessionPlayerState.SKIP) {
        content = <div className="text-3xl italic font-medium text-white">Skipping inactivity</div>
    }
    if (currentPlayerState === SessionPlayerState.SKIP_TO_MATCHING_EVENT) {
        content = <div className="text-3xl italic font-medium text-white">Skipping to filtered event</div>
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
            <SeekIndicator />
        </div>
    )
}
