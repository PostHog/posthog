import './SessionRecordingPlayer.scss'

import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'
import { useRef } from 'react'

import { MatchingEventsMatchType } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { PlayerSidebar } from './PlayerSidebar'
import { PurePlayer } from './PurePlayer'
import { playerSettingsLogic } from './playerSettingsLogic'
import {
    SessionRecordingPlayerLogicProps,
    SessionRecordingPlayerMode,
    sessionRecordingPlayerLogic,
} from './sessionRecordingPlayerLogic'

export { createPlaybackSpeedKey } from './PurePlayer'

export interface SessionRecordingPlayerProps extends SessionRecordingPlayerLogicProps {
    noMeta?: boolean
    noBorder?: boolean
    noInspector?: boolean
    matchingEventsMatchType?: MatchingEventsMatchType
    accessToken?: string
}

function SessionRecordingPlayerInternal({
    noMeta,
    noBorder,
    noInspector,
    playerRef,
}: {
    noMeta: boolean
    noBorder: boolean
    noInspector: boolean
    playerRef: React.RefObject<HTMLDivElement>
}): JSX.Element {
    const { isVerticallyStacked, sidebarOpen } = useValues(playerSettingsLogic)

    return (
        <div
            className={clsx('SessionRecordingPlayerWrapper', {
                'SessionRecordingPlayerWrapper--stacked-vertically': sidebarOpen && isVerticallyStacked,
            })}
        >
            <PurePlayer noMeta={noMeta} noBorder={noBorder} playerRef={playerRef} />
            {!noInspector && <PlayerSidebar />}
        </div>
    )
}

export function SessionRecordingPlayer(props: SessionRecordingPlayerProps): JSX.Element {
    const {
        sessionRecordingId,
        sessionRecordingData,
        playerKey,
        noMeta = false,
        matchingEventsMatchType,
        noBorder = false,
        noInspector = false,
        autoPlay = true,
        mode = SessionRecordingPlayerMode.Standard,
        accessToken,
        onRecordingDeleted,
        playNextRecording,
        metaControls,
    } = props

    const playerRef = useRef<HTMLDivElement>(null)

    const logicProps: SessionRecordingPlayerLogicProps = {
        sessionRecordingId,
        playerKey,
        matchingEventsMatchType,
        sessionRecordingData,
        autoPlay,
        noInspector,
        mode,
        playerRef,
        accessToken,
        onRecordingDeleted,
        playNextRecording,
        metaControls,
    }

    return (
        <BindLogic logic={sessionRecordingPlayerLogic} props={logicProps}>
            <SessionRecordingPlayerInternal
                noMeta={noMeta}
                noBorder={noBorder}
                noInspector={noInspector}
                playerRef={playerRef}
            />
        </BindLogic>
    )
}
