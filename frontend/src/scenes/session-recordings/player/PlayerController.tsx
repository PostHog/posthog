import React from 'react'
import { useActions, useValues } from 'kea'
import screenfull from 'screenfull'
import {
    PLAYBACK_SPEEDS,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { Tooltip } from 'antd'
import { SessionPlayerState } from '~/types'
import { IconFullscreen, IconPause, IconPlay, IconSeekBack } from 'scenes/session-recordings/player/icons'
import { Slider } from 'scenes/session-recordings/player/Slider'
import { colonDelimitedDuration } from 'lib/utils'

interface PlayerControllerProps {
    toggleFullScreen: () => void
}

export function PlayerController({ toggleFullScreen }: PlayerControllerProps): JSX.Element {
    const { togglePlayPause, seek, seekBackward, seekForward, setSpeed } = useActions(sessionRecordingPlayerLogic)
    const { currentPlayerState, jumpTimeMs, meta, time, speed, sessionPlayerDataLoading } =
        useValues(sessionRecordingPlayerLogic)

    return (
        <div className="ph-rrweb-bottom">
            <div className="ph-rrweb-controller">
                <div>
                    <Tooltip placement="top" overlayInnerStyle={{ minHeight: 'auto' }} overlay="Play/pause (space)">
                        <span>
                            {currentPlayerState === SessionPlayerState.PLAY ||
                            currentPlayerState === SessionPlayerState.SKIP ? (
                                <IconPause
                                    onClick={togglePlayPause}
                                    className="ph-rrweb-controller-icon ph-rrweb-controller-icon-play-pause"
                                />
                            ) : (
                                <IconPlay
                                    onClick={togglePlayPause}
                                    className="ph-rrweb-controller-icon ph-rrweb-controller-icon-play-pause"
                                />
                            )}
                        </span>
                    </Tooltip>
                    <Tooltip
                        placement="top"
                        overlayInnerStyle={{ minHeight: 'auto' }}
                        overlay={`Back ${jumpTimeMs / 1000}s (← left arrow)`}
                    >
                        <span>
                            <IconSeekBack onClick={seekBackward} />
                        </span>
                    </Tooltip>
                    <Tooltip
                        placement="top"
                        overlayInnerStyle={{ minHeight: 'auto' }}
                        overlay={`Forward ${jumpTimeMs / 1000}s (→ right arrow)`}
                    >
                        <span>
                            <IconSeekBack onClick={seekForward} />
                        </span>
                    </Tooltip>
                    <span className="ph-rrweb-timestamp">
                        {colonDelimitedDuration(time.current / 1000)} /{' '}
                        {sessionPlayerDataLoading ? '--:--:--' : colonDelimitedDuration(meta.totalTime / 1000)}
                    </span>
                </div>
                <div className="ph-rrweb-progress">
                    <Slider value={time.current} total={meta.totalTime} onChange={seek} />
                </div>
                <div style={{ justifyContent: 'flex-end' }}>
                    {PLAYBACK_SPEEDS.map((speedToggle, index) => (
                        <React.Fragment key={speedToggle}>
                            <Tooltip
                                placement="top"
                                overlayInnerStyle={{ minHeight: 'auto' }}
                                overlay={`${speedToggle}x speed (${index + 1})`}
                            >
                                <span
                                    className="ph-rrweb-speed-toggle"
                                    style={{
                                        fontWeight: speedToggle === speed ? 'bold' : 'normal',
                                    }}
                                    onClick={() => setSpeed(speedToggle)}
                                >
                                    {speedToggle}x
                                </span>
                            </Tooltip>
                        </React.Fragment>
                    ))}
                    {screenfull.isEnabled && (
                        <Tooltip placement="top" overlayInnerStyle={{ minHeight: 'auto' }} overlay="Full screen (f)">
                            <span>
                                <IconFullscreen onClick={toggleFullScreen} />
                            </span>
                        </Tooltip>
                    )}
                </div>
            </div>
        </div>
    )
}
