import './SessionRecordingPlayer.scss'

import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'
import { useRef } from 'react'

import { MatchingEventsMatchType } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { AnalysisNudge } from 'products/replay_vision/frontend/components/AnalysisNudge'
import { ObservationsDock } from 'products/replay_vision/frontend/components/ObservationsDock'
import { visionSurfaceShown } from 'products/replay_vision/frontend/utils/visionSurface'

import { playerSettingsLogic } from './playerSettingsLogic'
import { PlayerSidebar } from './PlayerSidebar'
import { PurePlayer } from './PurePlayer'
import {
    SessionRecordingPlayerLogicProps,
    SessionRecordingPlayerMode,
    sessionRecordingPlayerLogic,
} from './sessionRecordingPlayerLogic'

export { createPlaybackSpeedKey } from './PurePlayer'

export interface SessionRecordingPlayerProps extends SessionRecordingPlayerLogicProps {
    noMeta?: boolean
    noBorder?: boolean
    noDock?: boolean
    withSidebar?: boolean
    matchingEventsMatchType?: MatchingEventsMatchType
    accessToken?: string
    /** Shown in place of the generic not-found page when the recording cannot be loaded. */
    notFoundState?: JSX.Element
}

export function SessionRecordingPlayer(props: SessionRecordingPlayerProps): JSX.Element {
    const {
        sessionRecordingId,
        sessionRecordingData,
        playerKey,
        noMeta = false,
        matchingEventsMatchType,
        noBorder = false,
        noDock = false,
        withSidebar = true,
        autoPlay = true,
        mode = SessionRecordingPlayerMode.Standard,
        pinned,
        setPinned,
        accessToken,
        onRecordingDeleted,
        playNextRecording,
        skipToFirstMatchingEvent,
        notFoundState,
    } = props

    const playerRef = useRef<HTMLDivElement>(null)

    const logicProps: SessionRecordingPlayerLogicProps = {
        sessionRecordingId,
        playerKey,
        matchingEventsMatchType,
        sessionRecordingData,
        autoPlay,
        withSidebar,
        noMeta,
        noDock,
        mode,
        playerRef,
        pinned,
        setPinned,
        accessToken,
        onRecordingDeleted,
        playNextRecording,
        skipToFirstMatchingEvent,
    }

    return (
        <BindLogic logic={sessionRecordingPlayerLogic} props={logicProps}>
            <SessionRecordingPlayerInternal
                notFoundState={notFoundState}
                noMeta={noMeta}
                noBorder={noBorder}
                withSidebar={withSidebar}
                playerRef={playerRef}
            />
        </BindLogic>
    )
}

function SessionRecordingPlayerInternal({
    noMeta,
    noBorder,
    withSidebar,
    playerRef,
    notFoundState,
}: {
    noMeta: boolean
    noBorder: boolean
    withSidebar: boolean
    playerRef: React.RefObject<HTMLDivElement>
    notFoundState?: JSX.Element
}): JSX.Element {
    const { isVerticallyStacked, sidebarOpen } = useValues(playerSettingsLogic)
    const { logicProps } = useValues(sessionRecordingPlayerLogic)

    return (
        <div
            ref={playerRef}
            className={clsx('SessionRecordingPlayerWrapper', {
                'SessionRecordingPlayerWrapper--stacked-vertically': withSidebar && sidebarOpen && isVerticallyStacked,
            })}
        >
            <div className="relative flex flex-col flex-1 min-w-0 min-h-0">
                <PurePlayer noMeta={noMeta} noBorder={noBorder} notFoundState={notFoundState} />
                {visionSurfaceShown(logicProps) && (
                    <>
                        <ObservationsDock />
                        <AnalysisNudge />
                    </>
                )}
            </div>
            {withSidebar && <PlayerSidebar />}
        </div>
    )
}
