import './SessionRecordingPlayer.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { useRef } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { playerUsesWatchLayout } from 'scenes/session-recordings/playlist/replayLayout'
import { MatchingEventsMatchType } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { userLogic } from 'scenes/userLogic'

import { SessionRecordingSidebarStacking } from '~/types'

import { SummarizeRecordingBar } from 'products/replay_vision/frontend/components/SummarizeRecordingBar'
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
import { useLinkedIssuesAvailable } from './sidebar/useLinkedIssuesAvailable'
import { debugTabKeys } from './watch/DebugTabBar'
import { WatchPanel } from './watch/WatchPanel'

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
        watchLayout,
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
        watchLayout,
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
    const { isVerticallyStacked, sidebarOpen, debugMode, replayLayout, watchDebugDock } = useValues(playerSettingsLogic)
    const { setWatchDebugDock } = useActions(playerSettingsLogic)
    const { logicProps, isFullScreen } = useValues(sessionRecordingPlayerLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { user } = useValues(userLogic)
    const linkedIssuesAvailable = useLinkedIssuesAvailable()
    const showDebugReplayButton = featureFlags[FEATURE_FLAGS.REPLAY_DEBUG_WITH_AI] || user?.is_impersonated
    // The player modal covers the side panel, so the conversation would open out of sight.
    const debugReplayAction = showDebugReplayButton && logicProps.playerKey !== 'modal' ? <DebugReplayButton /> : null

    if (playerUsesWatchLayout(replayLayout, logicProps)) {
        const rightDock = debugMode && watchDebugDock === 'right' && !isFullScreen
        return (
            <div
                ref={playerRef}
                className={clsx('SessionRecordingPlayerWrapper SessionRecordingPlayerWrapper--watch', {
                    'SessionRecordingPlayerWrapper--watch-right-dock': rightDock,
                })}
            >
                <div className="SessionRecordingPlayerWrapper__column">
                    <div
                        className={clsx(
                            'SessionRecordingPlayerWrapper__player',
                            isFullScreen && 'SessionRecordingPlayerWrapper__player--fullscreen'
                        )}
                    >
                        <PurePlayer noMeta={noMeta} noBorder={noBorder} />
                    </div>
                    {!isFullScreen && <WatchPanel summaryActions={debugReplayAction} />}
                </div>
                {rightDock && (
                    <PlayerSidebar
                        tabs={debugTabKeys(linkedIssuesAvailable)}
                        stacking={SessionRecordingSidebarStacking.Horizontal}
                        onToggleStacking={() => setWatchDebugDock('bottom')}
                    />
                )}
            </div>
        )
    }

    return (
        <div
            ref={playerRef}
            className={clsx('SessionRecordingPlayerWrapper', {
                'SessionRecordingPlayerWrapper--stacked-vertically': withSidebar && sidebarOpen && isVerticallyStacked,
            })}
        >
            <div className="relative flex flex-col flex-1 min-w-0 min-h-0">
                <PurePlayer noMeta={noMeta} noBorder={noBorder} />
                {visionSurfaceShown(logicProps) && <SummarizeRecordingBar extraActions={debugReplayAction} />}
            </div>
            {withSidebar && <PlayerSidebar />}
        </div>
    )
}
