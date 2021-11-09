import React from 'react'
import { Tooltip } from 'antd'
import { IconSeekBack, IconSeekForward } from 'scenes/session-recordings/player/icons'
import { colonDelimitedDuration } from 'lib/utils'
import { useActions, useValues } from 'kea'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

export function Timestamp(): JSX.Element {
    const { seekBackward, seekForward } = useActions(sessionRecordingPlayerLogic)
    const { jumpTimeMs, meta, zeroOffsetTime } = useValues(sessionRecordingPlayerLogic)
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
                {colonDelimitedDuration(zeroOffsetTime.current / 1000)} /{' '}
                {colonDelimitedDuration(meta.totalTime / 1000)}
            </div>
        </>
    )
}
