import './SessionRecordingPlayer.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { useRef } from 'react'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { MatchingEventsMatchType } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { PurePlayer } from './PurePlayer'
import { playerSettingsLogic } from './playerSettingsLogic'
import {
    SessionRecordingPlayerLogicProps,
    SessionRecordingPlayerMode,
    sessionRecordingPlayerLogic,
} from './sessionRecordingPlayerLogic'
import { PlayerSidebarContent } from './sidebar/PlayerSidebarContent'

export interface SessionRecordingPlayerProps extends SessionRecordingPlayerLogicProps {
    noMeta?: boolean
    noBorder?: boolean
    noInspector?: boolean
    matchingEventsMatchType?: MatchingEventsMatchType
    accessToken?: string
}

export { createPlaybackSpeedKey } from './PurePlayer'

function SessionRecordingPlayerInternal({
    noMeta,
    noBorder,
    noInspector,
}: {
    noMeta: boolean
    noBorder: boolean
    noInspector: boolean
}): JSX.Element {
    const activityRef = useRef<HTMLDivElement>(null)

    const { sidebarOpen, isVerticallyStacked } = useValues(playerSettingsLogic)
    const { setSidebarOpen } = useActions(playerSettingsLogic)

    const logicKey = `player-sidebar-${isVerticallyStacked ? 'vertical' : 'horizontal'}`

    const resizerLogicProps: ResizerLogicProps = {
        logicKey,
        containerRef: activityRef,
        persistent: true,
        closeThreshold: 100,
        placement: isVerticallyStacked ? 'top' : 'left',
        onToggleClosed: (shouldBeClosed) => setSidebarOpen(!shouldBeClosed),
    }

    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    return (
        <div
            className={clsx(
                'SessionRecordingPlayer__wrapper flex h-full w-full',
                isVerticallyStacked ? 'flex-col' : 'flex-row'
            )}
        >
            <PurePlayer noMeta={noMeta} noBorder={noBorder} />
            {!noInspector && sidebarOpen && (
                <>
                    <div className={clsx('relative shrink-0', isVerticallyStacked ? 'h-2 w-full' : 'w-2 h-full')}>
                        <Resizer
                            logicKey={logicKey}
                            placement={isVerticallyStacked ? 'top' : 'left'}
                            containerRef={activityRef}
                            closeThreshold={100}
                            offset="50%"
                            className={clsx('SessionRecordingPlayer__resizer', isVerticallyStacked ? 'mx-1' : 'my-1')}
                        />
                    </div>
                    <div
                        ref={activityRef}
                        className={clsx(
                            'SessionActivity shrink-0',
                            isVerticallyStacked ? 'w-full' : 'min-w-80 max-w-[95%]'
                        )}
                        // eslint-disable-next-line react/forbid-dom-props
                        style={
                            isVerticallyStacked
                                ? { height: desiredSize ?? undefined, minHeight: 210 }
                                : { width: desiredSize ?? undefined }
                        }
                    >
                        <div className="flex flex-col h-full overflow-hidden bg-surface-primary border border-primary rounded">
                            <PlayerSidebarContent />
                        </div>
                    </div>
                </>
            )}
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
        playlistLogic,
        mode = SessionRecordingPlayerMode.Standard,
        pinned,
        setPinned,
        accessToken,
        playerRef,
        onRecordingDeleted,
    } = props

    const logicProps: SessionRecordingPlayerLogicProps = {
        sessionRecordingId,
        playerKey,
        matchingEventsMatchType,
        sessionRecordingData,
        autoPlay,
        noInspector,
        playlistLogic,
        mode,
        playerRef,
        pinned,
        setPinned,
        accessToken,
        onRecordingDeleted,
    }

    return (
        <BindLogic logic={sessionRecordingPlayerLogic} props={logicProps}>
            <SessionRecordingPlayerInternal noMeta={noMeta} noBorder={noBorder} noInspector={noInspector} />
        </BindLogic>
    )
}
