import React, { useRef } from 'react'
import { useActions, useValues } from 'kea'
import {
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { Row, Select, Switch } from 'antd'
import { SessionPlayerState, SessionRecordingPlayerProps, SessionRecordingTab } from '~/types'
import { IconPause, IconPlay } from 'scenes/session-recordings/player/icons'
import { Seekbar } from 'scenes/session-recordings/player/Seekbar'
import { SeekBack, SeekForward, Timestamp } from 'scenes/session-recordings/player/Time'
import { LemonButton, LemonButtonWithPopup } from 'lib/components/LemonButton'
import { IconSettings, IconTerminal, UnverifiedEvent } from 'lib/components/icons'
import { LemonSwitch } from 'lib/components/LemonSwitch/LemonSwitch'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

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
                    <IconPause
                        onClick={togglePlayPause}
                        className="rrweb-controller-icon ph-rrweb-controller-icon-play-pause"
                        style={isSmallScreen ? {} : { marginRight: '0.5rem' }}
                    />
                ) : (
                    <IconPlay
                        onClick={togglePlayPause}
                        className="rrweb-controller-icon ph-rrweb-controller-icon-play-pause"
                        style={isSmallScreen ? {} : { marginRight: '0.5rem' }}
                    />
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
    const { togglePlayPause, setSpeed, setSkipInactivitySetting, setTab } = useActions(
        sessionRecordingPlayerLogic({ sessionRecordingId, playerKey })
    )
    const { currentPlayerState, speed, isSmallScreen, skipInactivitySetting, tab } = useValues(
        sessionRecordingPlayerLogic({ sessionRecordingId, playerKey })
    )
    const { featureFlags } = useValues(featureFlagLogic)
    const speedSelectRef = useRef<HTMLDivElement | null>(null)

    return (
        <div className="rrweb-controller">
            <div className="rrweb-controller__top" data-attr="rrweb-controller">
                {!isSmallScreen && <Timestamp sessionRecordingId={sessionRecordingId} playerKey={playerKey} />}
                <Seekbar sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
            </div>
            <Row className="rrweb-controller__bottom" wrap={false} justify="space-between" align="middle">
                <Row wrap={false} className="space-x-2" style={{ width: '50%' }}>
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
                </Row>
                <Row wrap={false} className="gap-2 mx-2">
                    <SeekBack sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
                    <LemonButton status="primary-alt" size="small">
                        {[SessionPlayerState.PLAY, SessionPlayerState.SKIP].includes(currentPlayerState) ? (
                            <IconPause onClick={togglePlayPause} className="rrweb-controller-icon" />
                        ) : (
                            <IconPlay onClick={togglePlayPause} className="rrweb-controller-icon " />
                        )}
                    </LemonButton>
                    <SeekForward sessionRecordingId={sessionRecordingId} playerKey={playerKey} />
                </Row>
                <Row wrap={false} style={{ width: '50%' }} justify="end" align="middle">
                    <LemonButtonWithPopup
                        icon={<IconSettings />}
                        size="small"
                        sideIcon={null}
                        popup={{
                            overlay: (
                                <>
                                    <div className="p-2">
                                        <LemonSwitch
                                            label="Skip inactivity"
                                            checked={skipInactivitySetting}
                                            onChange={() => {
                                                setSkipInactivitySetting(!skipInactivitySetting)
                                            }}
                                        />
                                    </div>
                                    <LemonButtonWithPopup
                                        data-attr="session-recording-speed-select"
                                        className="session-recording-speed-select"
                                        fullWidth
                                        status="stealth"
                                        popup={{
                                            overlay: (
                                                <>
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
                                                </>
                                            ),
                                            placement: 'right-start',
                                            closeOnClickInside: false,
                                            ref: speedSelectRef,
                                        }}
                                    >
                                        Playback speed
                                    </LemonButtonWithPopup>
                                </>
                            ),
                            closeOnClickInside: false,
                            additionalRefs: [speedSelectRef],
                            placement: 'bottom-end',
                        }}
                    >
                        Settings
                    </LemonButtonWithPopup>
                </Row>
            </Row>
        </div>
    )
}
