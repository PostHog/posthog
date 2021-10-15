import { Row } from 'antd'
import React from 'react'
import { useValues } from 'kea'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import { PlayerFrame } from 'scenes/session-recordings/player/PlayerFrame'
import { PlayerController } from 'scenes/session-recordings/player/PlayerController'
import { PlayerEvents } from 'scenes/session-recordings/player/PlayerEvents'

export function SessionRecordingPlayerV2(): JSX.Element {
    const {} = useValues(sessionRecordingPlayerLogic)

    return (
        <div className="session-player">
            <Row gutter={16} style={{ height: '100%' }}>
                <h1>Session Player V2</h1>
                <PlayerFrame />
                <PlayerController />
                <PlayerEvents />
            </Row>
        </div>
    )
}
