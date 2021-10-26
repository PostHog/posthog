import React from 'react'
import { useActions, useValues } from 'kea'
import {
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { Select, Switch } from 'antd'
import { SessionPlayerState } from '~/types'
import { IconPause, IconPlay } from 'scenes/session-recordings/player/icons'
import { Seekbar } from 'scenes/session-recordings/player/Seekbar'
import { Timestamp } from 'scenes/session-recordings/player/Timestamp'

export function PlayerController(): JSX.Element {
    const { togglePlayPause, setSpeed } = useActions(sessionRecordingPlayerLogic)
    const { currentPlayerState, speed, isSmallScreen } = useValues(sessionRecordingPlayerLogic)

    return (
        <div className="rrweb-controller">
            <span>
                {currentPlayerState === SessionPlayerState.PLAY || currentPlayerState === SessionPlayerState.SKIP ? (
                    <IconPause
                        onClick={togglePlayPause}
                        className="rrweb-controller-icon ph-rrweb-controller-icon-play-pause"
                    />
                ) : (
                    <IconPlay
                        onClick={togglePlayPause}
                        className="rrweb-controller-icon ph-rrweb-controller-icon-play-pause"
                    />
                )}
            </span>
            {!isSmallScreen && <Timestamp />}
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
            <div className="rrweb-inactivity-toggle">
                <span className="inactivity-label">Skip inactivity</span>
                <Switch disabled size="small" />
            </div>
        </div>
    )
}
