import { Row } from 'antd'
import React from 'react'
import { useValues } from 'kea'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import { PlayerFrame } from 'scenes/sessionRecordings/player/PlayerFrame'
import { PlayerController } from 'scenes/sessionRecordings/player/PlayerController'
import { PlayerEvents } from 'scenes/sessionRecordings/player/PlayerEvents'

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
