import React, { useRef } from 'react'
import { useActions, useValues } from 'kea'
import {
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { Row, Select, Switch } from 'antd'
import { SessionPlayerState, SessionRecordingProps, SessionRecordingTab } from '~/types'
import { IconPause, IconPlay } from 'scenes/session-recordings/player/icons'
import { Seekbar } from 'scenes/session-recordings/player/Seekbar'
import { SeekBack, SeekForward, Timestamp } from 'scenes/session-recordings/player/Time'
import { LemonButton, LemonButtonWithPopup } from 'lib/components/LemonButton'
import { IconSettings, IconTerminal, UnverifiedEvent } from 'lib/components/icons'
import { LemonSwitch } from 'lib/components/LemonSwitch/LemonSwitch'

export function PlayerControllerV2({ sessionRecordingId }: SessionRecordingProps): JSX.Element {
    const { togglePlayPause, setSpeed, setSkipInactivitySetting } = useActions(
        sessionRecordingPlayerLogic({ sessionRecordingId })
    )
    const { currentPlayerState, speed, isSmallScreen, skipInactivitySetting } = useValues(
        sessionRecordingPlayerLogic({ sessionRecordingId })
    )

    return (
        <div className="rrweb-controller" data-tooltip="recording-player">
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
                    <SeekBack sessionRecordingId={sessionRecordingId} style={{ marginRight: '0.25rem' }} />
                    <SeekForward sessionRecordingId={sessionRecordingId} style={{ marginRight: '0.5rem' }} />
                    <Timestamp sessionRecordingId={sessionRecordingId} />
                </>
            )}
            <div className="rrweb-progress">
                <Seekbar sessionRecordingId={sessionRecordingId} />
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

export function PlayerControllerV3({ sessionRecordingId }: SessionRecordingProps): JSX.Element {
    const { togglePlayPause, setSpeed, setSkipInactivitySetting, setTab } = useActions(
        sessionRecordingPlayerLogic({ sessionRecordingId })
    )
    const { currentPlayerState, speed, isSmallScreen, skipInactivitySetting, tab } = useValues(
        sessionRecordingPlayerLogic({ sessionRecordingId })
    )
    const speedSelectRef = useRef<HTMLDivElement | null>(null)

    return (
        <div className="rrweb-controller">
            <div className="rrweb-controller__top" data-tooltip="recording-player">
                {!isSmallScreen && <Timestamp sessionRecordingId={sessionRecordingId} />}
                <Seekbar sessionRecordingId={sessionRecordingId} />
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
                </Row>
                <Row wrap={false} className="gap-2 mx-2">
                    <SeekBack sessionRecordingId={sessionRecordingId} />
                    <LemonButton status="primary-alt" size="small">
                        {[SessionPlayerState.PLAY, SessionPlayerState.SKIP].includes(currentPlayerState) ? (
                            <IconPause onClick={togglePlayPause} className="rrweb-controller-icon" />
                        ) : (
                            <IconPlay onClick={togglePlayPause} className="rrweb-controller-icon " />
                        )}
                    </LemonButton>
                    <SeekForward sessionRecordingId={sessionRecordingId} />
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
