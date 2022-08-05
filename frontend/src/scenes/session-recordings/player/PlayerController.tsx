import React, { useRef } from 'react'
import { useActions, useValues } from 'kea'
import {
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { Row, Select, Switch } from 'antd'
import { SessionPlayerState, SessionRecordingTab } from '~/types'
import { IconPause, IconPlay } from 'scenes/session-recordings/player/icons'
import { Seekbar } from 'scenes/session-recordings/player/Seekbar'
import { SeekBack, SeekForward, Timestamp } from 'scenes/session-recordings/player/Time'
import { LemonButton, LemonButtonWithPopup } from 'lib/components/LemonButton'
import { IconSettings, IconTerminal, UnverifiedEvent } from 'lib/components/icons'
import { LemonSwitch } from 'lib/components/LemonSwitch/LemonSwitch'

export function PlayerControllerV2(): JSX.Element {
    const { togglePlayPause, setSpeed, setSkipInactivitySetting } = useActions(sessionRecordingPlayerLogic)
    const { currentPlayerState, speed, isSmallScreen, skipInactivitySetting } = useValues(sessionRecordingPlayerLogic)

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
                    <SeekBack style={{ marginRight: '0.25rem' }} />
                    <SeekForward style={{ marginRight: '0.5rem' }} />
                    <Timestamp />
                </>
            )}
            <div className="rrweb-progress">
                <Seekbar />
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

export function PlayerControllerV3(): JSX.Element {
    const { togglePlayPause, setSpeed, setSkipInactivitySetting, setTab } = useActions(sessionRecordingPlayerLogic)
    const { currentPlayerState, speed, isSmallScreen, skipInactivitySetting, tab } =
        useValues(sessionRecordingPlayerLogic)
    const speedSelectRef = useRef<HTMLDivElement | null>(null)

    return (
        <div className="rrweb-controller">
            <div className="rrweb-controller__top" data-tooltip="recording-player">
                {!isSmallScreen && <Timestamp />}
                <Seekbar />
            </div>
            <Row className="rrweb-controller__bottom" wrap={false} justify="space-between" align="middle">
                <Row wrap={false} style={{ width: '50%' }}>
                    <LemonButton
                        size="small"
                        icon={<UnverifiedEvent />}
                        type={tab === SessionRecordingTab.EVENTS ? 'highlighted' : 'alt'}
                        onClick={() => setTab(SessionRecordingTab.EVENTS)}
                        style={{ marginRight: '0.5rem' }}
                    >
                        Events
                    </LemonButton>
                    <LemonButton
                        size="small"
                        icon={<IconTerminal />}
                        type={tab === SessionRecordingTab.CONSOLE ? 'highlighted' : 'alt'}
                        onClick={() => {
                            setTab(SessionRecordingTab.CONSOLE)
                        }}
                    >
                        Console
                    </LemonButton>
                </Row>
                <Row wrap={false} style={{ margin: '0 1rem' }}>
                    <SeekBack />
                    <LemonButton
                        type="alt"
                        icon={
                            [SessionPlayerState.PLAY, SessionPlayerState.SKIP].includes(currentPlayerState) ? (
                                <IconPause
                                    onClick={togglePlayPause}
                                    className="rrweb-controller-icon ph-rrweb-controller-icon-play-pause"
                                    style={{ margin: '0 1.25rem' }}
                                />
                            ) : (
                                <IconPlay
                                    onClick={togglePlayPause}
                                    className="rrweb-controller-icon ph-rrweb-controller-icon-play-pause"
                                />
                            )
                        }
                        style={{ margin: '0 1.25rem' }}
                    />
                    <SeekForward />
                </Row>
                <Row wrap={false} style={{ width: '50%' }} justify="end" align="middle">
                    <LemonButtonWithPopup
                        icon={<IconSettings />}
                        size="small"
                        sideIcon={null}
                        popup={{
                            overlay: (
                                <>
                                    <LemonSwitch
                                        label="Skip inactivity"
                                        checked={skipInactivitySetting}
                                        onChange={() => {
                                            setSkipInactivitySetting(!skipInactivitySetting)
                                        }}
                                    />
                                    <LemonButtonWithPopup
                                        data-attr="session-recording-speed-select"
                                        className="session-recording-speed-select"
                                        type="stealth"
                                        popup={{
                                            overlay: (
                                                <>
                                                    {PLAYBACK_SPEEDS.map((speedToggle) => (
                                                        <LemonButton
                                                            fullWidth
                                                            type={speed === speedToggle ? 'highlighted' : 'stealth'}
                                                            key={speedToggle}
                                                            value={speedToggle}
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
