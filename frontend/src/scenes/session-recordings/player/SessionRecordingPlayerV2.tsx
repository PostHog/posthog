import React, { useRef } from 'react'
import { useValues } from 'kea'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'
import { PlayerFrame } from 'scenes/session-recordings/player/PlayerFrame'
import { PlayerController } from 'scenes/session-recordings/player/PlayerController'
import { PlayerEvents } from 'scenes/session-recordings/player/PlayerEvents'

export function SessionRecordingPlayerV2(): JSX.Element {
    const {} = useValues(sessionRecordingPlayerLogic)
    const frame = useRef<HTMLDivElement | null>(null)
    const wrapper = useRef<HTMLDivElement | null>(null)

    return (
        <div className="session-player" ref={wrapper}>
            <h1>Session Player V2</h1>
            <PlayerFrame ref={frame} />
            <PlayerController />
            <PlayerEvents />
        </div>
    )
}
