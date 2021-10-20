import React from 'react'
import { useActions, useValues } from 'kea'
import {
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { Select, Switch, Tooltip } from 'antd'
import { SessionPlayerState } from '~/types'
import { IconPause, IconPlay, IconSeekBack, IconSeekForward } from 'scenes/session-recordings/player/icons'
import { Slider } from 'scenes/session-recordings/player/Slider'
import { colonDelimitedDuration } from 'lib/utils'

export function PlayerController(): JSX.Element {
    const { togglePlayPause, seekBackward, seekForward, setSpeed } = useActions(sessionRecordingPlayerLogic)
    const { currentPlayerState, jumpTimeMs, meta, time, speed } = useValues(sessionRecordingPlayerLogic)

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
            <Tooltip
                placement="top"
                overlayInnerStyle={{ minHeight: 'auto' }}
                overlay={`Back ${jumpTimeMs / 1000}s (← left arrow)`}
            >
                <span>
                    <IconSeekBack onClick={seekBackward} time={jumpTimeMs / 1000} />
                </span>
            </Tooltip>
            <Tooltip
                placement="top"
                overlayInnerStyle={{ minHeight: 'auto' }}
                overlay={`Forward ${jumpTimeMs / 1000}s (→ right arrow)`}
            >
                <span>
                    <IconSeekForward onClick={seekForward} time={jumpTimeMs / 1000} />
                </span>
            </Tooltip>
            <div className="rrweb-timestamp">
                {colonDelimitedDuration(time.current / 1000)} / {colonDelimitedDuration(meta.totalTime / 1000)}
            </div>
            <div className="rrweb-progress">
                <Slider /*value={time.current} total={meta.totalTime} onChange={seek}*/ />
            </div>
            <Select
                onChange={(nextSpeed: number) => setSpeed(nextSpeed)}
                value={speed}
                dropdownMatchSelectWidth={false}
                size="small"
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
