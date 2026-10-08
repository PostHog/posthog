import './SessionRecordingPlayer.scss'

import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'
import { useRef } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { MatchingEventsMatchType } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { ObservationsDock } from 'products/replay_vision/frontend/components/ObservationsDock'
import { visionSurfaceShown } from 'products/replay_vision/frontend/utils/visionSurface'

import { DebugReplayButton } from './player-meta/DebugReplayButton'
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
        exposureSkipExperimentId,
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
        exposureSkipExperimentId,
    }

    return (
        <BindLogic logic={sessionRecordingPlayerLogic} props={logicProps}>
            <SessionRecordingPlayerInternal
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
}: {
    noMeta: boolean
    noBorder: boolean
    withSidebar: boolean
    playerRef: React.RefObject<HTMLDivElement>
}): JSX.Element {
    const { isVerticallyStacked, sidebarOpen } = useValues(playerSettingsLogic)
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <div
            ref={playerRef}
            className={clsx('SessionRecordingPlayerWrapper', {
                'SessionRecordingPlayerWrapper--stacked-vertically': withSidebar && sidebarOpen && isVerticallyStacked,
            })}
        >
            <div className="relative flex flex-col flex-1 min-w-0 min-h-0">
                <PurePlayer noMeta={noMeta} noBorder={noBorder} />
                {visionSurfaceShown(logicProps) && (
                    <ObservationsDock
                        // The player modal covers the side panel, so the conversation would open out of sight.
                        extraActions={
                            featureFlags[FEATURE_FLAGS.REPLAY_DEBUG_WITH_AI] && logicProps.playerKey !== 'modal' ? (
                                <DebugReplayButton />
                            ) : null
                        }
                    />
                )}
            </div>
            {withSidebar && <PlayerSidebar />}
        </div>
    )
}
