import React, { CSSProperties } from 'react'
import { Tooltip } from 'antd'
import { IconSeekBack, IconSeekForward } from 'scenes/session-recordings/player/icons'
import { colonDelimitedDuration } from 'lib/utils'
import { useActions, useValues } from 'kea'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { seekbarLogic } from './seekbarLogic'
import { SessionRecordingPlayerProps } from '~/types'

interface TimeControlProps extends SessionRecordingPlayerProps {
    style?: CSSProperties
}

export function Timestamp({ style, sessionRecordingId, playerKey }: TimeControlProps): JSX.Element {
    const { currentPlayerTime, sessionPlayerData } = useValues(
        sessionRecordingPlayerLogic({ sessionRecordingId, playerKey })
    )
    const { isScrubbing, scrubbingTime } = useValues(seekbarLogic({ sessionRecordingId, playerKey }))

    return (
        <div className="rrweb-timestamp" style={style}>
            {colonDelimitedDuration(((isScrubbing ? scrubbingTime : currentPlayerTime) ?? 0) / 1000)} /{' '}
            {colonDelimitedDuration(Math.floor((sessionPlayerData?.metadata?.recordingDurationMs ?? 0) / 1000))}
        </div>
    )
}

export function SeekBack({ style, sessionRecordingId, playerKey }: TimeControlProps): JSX.Element {
    const { seekBackward } = useActions(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
    const { jumpTimeMs } = useValues(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
    return (
        <Tooltip
            placement="top"
            overlayInnerStyle={{ minHeight: 'auto' }}
            overlay={`Back ${jumpTimeMs / 1000}s (← left arrow)`}
        >
            <span>
                <IconSeekBack onClick={seekBackward} time={jumpTimeMs / 1000} style={style} />
            </span>
        </Tooltip>
    )
}

export function SeekForward({ style, sessionRecordingId, playerKey }: TimeControlProps): JSX.Element {
    const { seekForward } = useActions(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
    const { jumpTimeMs } = useValues(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
    return (
        <Tooltip
            placement="top"
            overlayInnerStyle={{ minHeight: 'auto' }}
            overlay={`Forward ${jumpTimeMs / 1000}s (→ right arrow)`}
        >
            <span>
                <IconSeekForward onClick={seekForward} time={jumpTimeMs / 1000} style={style} />
            </span>
        </Tooltip>
    )
}
