import './SessionRecordingsKiosk.scss'

import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { KioskPlayer } from './KioskPlayer'
import { sessionRecordingsKioskLogic } from './sessionRecordingsKioskLogic'

export const scene: SceneExport = {
    component: SessionRecordingsKiosk,
    logic: sessionRecordingsKioskLogic,
}

export function SessionRecordingsKiosk(): JSX.Element {
    const { recordingsLoading, hasRecordings } = useValues(sessionRecordingsKioskLogic)

    if (recordingsLoading) {
        return (
            <div className="SessionRecordingsKiosk SessionRecordingsKiosk--loading">
                <div className="SessionRecordingsKiosk__message">Loading session recordings...</div>
            </div>
        )
    }

    if (!hasRecordings) {
        return (
            <div className="SessionRecordingsKiosk SessionRecordingsKiosk--empty">
                <div className="SessionRecordingsKiosk__message">
                    <h2>No recordings available</h2>
                    <p>There are no unplayed session recordings to display.</p>
                    <p>
                        <Link to="/replay">Go to Session replay</Link>
                    </p>
                </div>
            </div>
        )
    }

    return (
        <div className="SessionRecordingsKiosk">
            <KioskPlayer />
        </div>
    )
}

export default SessionRecordingsKiosk
