import React from 'react'
import { Tooltip } from 'antd'
import { IconSeekBack, IconSeekForward } from 'scenes/session-recordings/player/icons'
import { colonDelimitedDuration } from 'lib/utils'
import { useActions, useValues } from 'kea'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { seekbarLogic } from './seekbarLogic'

export function Timestamp(): JSX.Element {
    const { seekBackward, seekForward } = useActions(sessionRecordingPlayerLogic)
    const { jumpTimeMs, currentPlayerTime, sessionPlayerData } = useValues(sessionRecordingPlayerLogic)
    const { isScrubbing, scrubbingTime } = useValues(seekbarLogic)

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
                {colonDelimitedDuration(((isScrubbing ? scrubbingTime : currentPlayerTime) ?? 0) / 1000)} /{' '}
                {colonDelimitedDuration(Math.floor((sessionPlayerData?.metadata?.recordingDurationMs ?? 0) / 1000))}
            </div>
        </>
    )
}
