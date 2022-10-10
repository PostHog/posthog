import React from 'react'
import { useActions, useValues } from 'kea'
import {
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { Select, Switch } from 'antd'
import { SessionPlayerState, SessionRecordingPlayerProps, SessionRecordingTab } from '~/types'
import { IconPause, IconPlay } from 'scenes/session-recordings/player/icons'
import { Seekbar } from 'scenes/session-recordings/player/Seekbar'
import { SeekBack, SeekForward, Timestamp } from 'scenes/session-recordings/player/Time'
import { LemonButton, LemonButtonWithPopup } from 'lib/components/LemonButton'
import { IconFullScreen, IconGauge, IconTerminal, UnverifiedEvent } from 'lib/components/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { Tooltip } from 'lib/components/Tooltip'

export function PlayerControllerV2({ sessionRecordingId, playerKey }: SessionRecordingPlayerProps): JSX.Element {
    const { togglePlayPause, setSpeed, setSkipInactivitySetting } = useActions(
        sessionRecordingPlayerLogic({ sessionRecordingId, playerKey })
    )
    const { currentPlayerState, speed, isSmallScreen, skipInactivitySetting } = useValues(
        sessionRecordingPlayerLogic({ sessionRecordingId, playerKey })
    )

    return (
        <div className="rrweb-controller" data-attr="rrweb-controller">
            <span>
                {currentPlayerState === SessionPlayerState.PLAY ? (
                    <IconPause onClick={togglePlayPause} style={isSmallScreen ? {} : { marginRight: '0.5rem' }} />
                ) : (
                    <IconPlay onClick={togglePlayPause} style={isSmallScreen ? {} : { marginRight: '0.5rem' }} />
                )}
            </span>
            {!isSmallScreen && (
                <>
                    <SeekBack
                        sessionRecordingId={sessionRecordingId}
                        style={{ marginRight: '0.25rem' }}
                        playerKey={playerKey}
                    />
                    <SeekForward
                        sessionRecordingId={sessionRecordingId}
                        style={{ marginRight: '0.5rem' }}
                        playerKey={playerKey}
                    />
                    <Timestamp sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
                </>
            )}
            <div className="rrweb-progress">
                <Seekbar sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
            </div>
            <Select
                onChange={(nextSpeed: number) => setSpeed(nextSpeed)}
                value={speed}
                dropdownMatchSelectWidth={false}
                size="small"
                defaultValue={1}
                className="rrweb-speed-toggle"
            >
                <Select.OptGroup label="Speed">
                    {PLAYBACK_SPEEDS.map((speedToggle) => (
                        <Select.Option key={speedToggle} value={speedToggle}>
                            {speedToggle}x
                        </Select.Option>
                    ))}
                </Select.OptGroup>
            </Select>
            <div
                onClick={() => {
                    setSkipInactivitySetting(!skipInactivitySetting)
                }}
                className="rrweb-inactivity-toggle"
            >
                <span className="inactivity-label">Skip inactivity</span>
                <Switch checked={skipInactivitySetting} size="small" />
            </div>
        </div>
    )
}

export function PlayerControllerV3({ sessionRecordingId, playerKey }: SessionRecordingPlayerProps): JSX.Element {
    const { togglePlayPause, setSpeed, setSkipInactivitySetting, setTab, setFullScreen } = useActions(
        sessionRecordingPlayerLogic({ sessionRecordingId, playerKey })
    )
    const { currentPlayerState, speed, isSmallScreen, skipInactivitySetting, tab, isFullScreen } = useValues(
        sessionRecordingPlayerLogic({ sessionRecordingId, playerKey })
    )
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <div className="PlayerControllerV3">
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
                                Events
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
                                    Console
                                </LemonButton>
                            )}
                        </>
                    )}
                </div>
                <div className="flex items-center gap-1">
                    <SeekBack sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
                    <LemonButton status="primary-alt" size="small">
                        {[SessionPlayerState.PLAY, SessionPlayerState.SKIP].includes(currentPlayerState) ? (
                            <IconPause onClick={togglePlayPause} />
                        ) : (
                            <IconPlay onClick={togglePlayPause} />
                        )}
                    </LemonButton>
                    <SeekForward sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
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
                        <span
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                transform: skipInactivitySetting ? undefined : 'rotateY(180deg)',
                            }}
                        >
                            <LemonButton
                                size="small"
                                status={skipInactivitySetting ? 'primary' : 'primary-alt'}
                                onClick={() => {
                                    setSkipInactivitySetting(!skipInactivitySetting)
                                }}
                            >
                                <IconGauge className="text-2xl" />
                            </LemonButton>
                        </span>
                    </Tooltip>
                    <Tooltip title={`${!isFullScreen ? 'Go' : 'exit'} full screen (F)`}>
                        <LemonButton
                            size="small"
                            status={'primary-alt'}
                            onClick={() => {
                                setFullScreen(!isFullScreen)
                            }}
                        >
                            <IconFullScreen className="text-2xl" />
                        </LemonButton>
                    </Tooltip>
                </div>
            </div>
        </div>
    )
}
