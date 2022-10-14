import React from 'react'
import { useActions, useValues } from 'kea'
import {
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { SessionPlayerState, SessionRecordingPlayerProps, SessionRecordingTab } from '~/types'
import { Seekbar } from 'scenes/session-recordings/player/Seekbar'
import { SeekSkip, Timestamp } from 'scenes/session-recordings/player/PlayerControllerTime'
import { LemonButton, LemonButtonWithPopup } from 'lib/components/LemonButton'
import {
    IconFullScreen,
    IconPause,
    IconPlay,
    IconSkipInactivity,
    IconTerminal,
    UnverifiedEvent,
} from 'lib/components/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { Tooltip } from 'lib/components/Tooltip'
import clsx from 'clsx'

export function PlayerController({ sessionRecordingId, playerKey }: SessionRecordingPlayerProps): JSX.Element {
    const { togglePlayPause, setSpeed, setSkipInactivitySetting, setTab, setIsFullScreen } = useActions(
        sessionRecordingPlayerLogic({ sessionRecordingId, playerKey })
    )
    const { currentPlayerState, speed, isSmallScreen, isSmallPlayer, skipInactivitySetting, tab, isFullScreen } =
        useValues(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <div className="p-3 bg-light flex flex-col select-none">
            <div className="flex items-center h-8 mb-2" data-attr="rrweb-controller">
                {!isSmallScreen && <Timestamp sessionRecordingId={sessionRecordingId} playerKey={playerKey} />}
                <Seekbar sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
            </div>
            <div className="flex justify-between items-center h-8 gap-2">
                <div className="flex items-center gap-2 flex-1">
                    {!isFullScreen && (
                        <>
                            <LemonButton
                                size="small"
                                icon={<UnverifiedEvent />}
                                status={tab === SessionRecordingTab.EVENTS ? 'primary' : 'primary-alt'}
                                active={tab === SessionRecordingTab.EVENTS}
                                onClick={() => setTab(SessionRecordingTab.EVENTS)}
                            >
                                {isSmallScreen || isSmallPlayer ? '' : 'Events'}
                            </LemonButton>
                            {featureFlags[FEATURE_FLAGS.SESSION_CONSOLE] && (
                                <LemonButton
                                    size="small"
                                    icon={<IconTerminal />}
                                    status={tab === SessionRecordingTab.CONSOLE ? 'primary' : 'primary-alt'}
                                    active={tab === SessionRecordingTab.CONSOLE}
                                    onClick={() => {
                                        setTab(SessionRecordingTab.CONSOLE)
                                    }}
                                >
                                    {isSmallScreen || isSmallPlayer ? '' : 'Console'}
                                </LemonButton>
                            )}
                        </>
                    )}
                </div>
                <div className="flex items-center gap-1">
                    <SeekSkip sessionRecordingId={sessionRecordingId} playerKey={playerKey} direction="backward" />
                    <LemonButton status="primary-alt" size="small" onClick={togglePlayPause}>
                        {[SessionPlayerState.PLAY, SessionPlayerState.SKIP].includes(currentPlayerState) ? (
                            <IconPause className="text-2xl" />
                        ) : (
                            <IconPlay className="text-2xl" />
                        )}
                    </LemonButton>
                    <SeekSkip sessionRecordingId={sessionRecordingId} playerKey={playerKey} direction="forward" />
                </div>
                <div className="flex items-center gap-1 flex-1 justify-end">
                    <Tooltip title={'Playback speed'}>
                        <LemonButtonWithPopup
                            data-attr="session-recording-speed-select"
                            popup={{
                                overlay: (
                                    <div className="space-y-px">
                                        {PLAYBACK_SPEEDS.map((speedToggle) => (
                                            <LemonButton
                                                fullWidth
                                                status="stealth"
                                                active={speed === speedToggle}
                                                key={speedToggle}
                                                onClick={() => {
                                                    setSpeed(speedToggle)
                                                }}
                                            >
                                                {speedToggle}x
                                            </LemonButton>
                                        ))}
                                    </div>
                                ),
                                closeOnClickInside: true,
                            }}
                            sideIcon={null}
                            size="small"
                            status="primary-alt"
                        >
                            {speed}x
                        </LemonButtonWithPopup>
                    </Tooltip>

                    <Tooltip title={`Skip inactivity (${skipInactivitySetting ? 'on' : 'off'})`}>
                        <LemonButton
                            size="small"
                            status="primary-alt"
                            onClick={() => {
                                setSkipInactivitySetting(!skipInactivitySetting)
                            }}
                        >
                            <IconSkipInactivity
                                className={clsx(
                                    'text-2xl',
                                    skipInactivitySetting ? 'text-primary' : 'text-primary-alt'
                                )}
                                enabled={skipInactivitySetting}
                            />
                        </LemonButton>
                    </Tooltip>
                    <Tooltip title={`${!isFullScreen ? 'Go' : 'exit'} full screen (F)`}>
                        <LemonButton
                            size="small"
                            status="primary-alt"
                            onClick={() => {
                                setIsFullScreen(!isFullScreen)
                            }}
                        >
                            <IconFullScreen
                                className={clsx('text-2xl', isFullScreen ? 'text-primary' : 'text-primary-alt')}
                            />
                        </LemonButton>
                    </Tooltip>
                </div>
            </div>
        </div>
    )
}
