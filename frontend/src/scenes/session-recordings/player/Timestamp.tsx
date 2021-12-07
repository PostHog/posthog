import React from 'react'
import { Tooltip } from 'antd'
import { IconSeekBack, IconSeekForward } from 'scenes/session-recordings/player/icons'
import { colonDelimitedDuration } from 'lib/utils'
import { useActions, useValues } from 'kea'
import {
    getPlayerTimeFromPlayerPosition,
    sessionRecordingPlayerLogic,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

export function Timestamp(): JSX.Element {
    const { seekBackward, seekForward } = useActions(sessionRecordingPlayerLogic)
    const { jumpTimeMs, currentPlayerPosition, sessionPlayerData } = useValues(sessionRecordingPlayerLogic)
    return (
        <>
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
                {colonDelimitedDuration(
                    Math.floor(
                        currentPlayerPosition
                            ? getPlayerTimeFromPlayerPosition(
                                  currentPlayerPosition,
                                  sessionPlayerData.metadata.segments
                              ) / 1000
                            : 0
                    )
                )}{' '}
                / {colonDelimitedDuration(Math.floor((sessionPlayerData?.metadata?.recordingDurationMs ?? 0) / 1000))}
            </div>
        </>
    )
}
