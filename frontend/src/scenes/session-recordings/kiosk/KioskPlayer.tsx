import './KioskPlayer.scss'

import { useActions, useValues } from 'kea'

import { SessionRecordingPlayer } from '../player/SessionRecordingPlayer'
import { SessionRecordingPlayerMode } from '../player/sessionRecordingPlayerLogic'
import { sessionRecordingsKioskLogic } from './sessionRecordingsKioskLogic'

export function KioskPlayer(): JSX.Element | null {
    const { currentRecordingId, currentRecording } = useValues(sessionRecordingsKioskLogic)
    const { advanceToNextRecording } = useActions(sessionRecordingsKioskLogic)

    const playerKey = `kiosk-player-${currentRecordingId}`

    if (!currentRecordingId || !currentRecording) {
        return (
            <div className="KioskPlayer KioskPlayer--loading">
                <div className="KioskPlayer__message">Loading recordings...</div>
            </div>
        )
    }

    return (
        <div className="KioskPlayer">
            <SessionRecordingPlayer
                playerKey={playerKey}
                sessionRecordingId={currentRecordingId}
                mode={SessionRecordingPlayerMode.Kiosk}
                autoPlay={true}
                withSidebar={false}
                noMeta={true}
                noBorder={true}
                playNextRecording={() => advanceToNextRecording()}
            />
        </div>
    )
}
