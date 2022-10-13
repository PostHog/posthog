import React from 'react'
import { Tooltip } from 'antd'
import { colonDelimitedDuration } from 'lib/utils'
import { useActions, useValues } from 'kea'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { seekbarLogic } from './seekbarLogic'
import { SessionRecordingPlayerProps } from '~/types'
import { LemonButton } from '@posthog/lemon-ui'
import { RedoOutlined, UndoOutlined } from '@ant-design/icons'

export function Timestamp({ sessionRecordingId, playerKey }: SessionRecordingPlayerProps): JSX.Element {
    const { currentPlayerTime, sessionPlayerData } = useValues(
        sessionRecordingPlayerLogic({ sessionRecordingId, playerKey })
    )
    const { isScrubbing, scrubbingTime } = useValues(seekbarLogic({ sessionRecordingId, playerKey }))

    return (
        <div className="whitespace-nowrap mr-4">
            {colonDelimitedDuration(((isScrubbing ? scrubbingTime : currentPlayerTime) ?? 0) / 1000)} /{' '}
            {colonDelimitedDuration(Math.floor((sessionPlayerData?.metadata?.recordingDurationMs ?? 0) / 1000))}
        </div>
    )
}

export function SeekBack({ sessionRecordingId, playerKey }: SessionRecordingPlayerProps): JSX.Element {
    const { seekBackward } = useActions(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
    const { jumpTimeMs } = useValues(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
    return (
        <Tooltip
            placement="top"
            overlayInnerStyle={{ minHeight: 'auto' }}
            overlay={`Back ${jumpTimeMs / 1000}s (← left arrow)`}
        >
            <LemonButton status="primary-alt" size="small" onClick={seekBackward}>
                <div className="PlayerControlSeekIcon">
                    <span className="PlayerControlSeekIcon__seconds">{jumpTimeMs / 1000}</span>
                    <UndoOutlined className="PlayerControlSeekIcon__icon" rotate={90} />
                </div>
            </LemonButton>
        </Tooltip>
    )
}

export function SeekForward({ sessionRecordingId, playerKey }: SessionRecordingPlayerProps): JSX.Element {
    const { seekForward } = useActions(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
    const { jumpTimeMs } = useValues(sessionRecordingPlayerLogic({ sessionRecordingId, playerKey }))
    return (
        <Tooltip
            placement="top"
            overlayInnerStyle={{ minHeight: 'auto' }}
            overlay={`Forward ${jumpTimeMs / 1000}s (→ right arrow)`}
        >
            <LemonButton status="primary-alt" size="small" onClick={seekForward}>
                <div className="PlayerControlSeekIcon">
                    <span className="PlayerControlSeekIcon__seconds">{jumpTimeMs / 1000}</span>
                    <RedoOutlined className="PlayerControlSeekIcon__icon" rotate={270} />
                </div>
            </LemonButton>
        </Tooltip>
    )
}
