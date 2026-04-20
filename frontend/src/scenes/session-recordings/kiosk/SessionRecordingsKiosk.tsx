import './SessionRecordingsKiosk.scss'

import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { KioskPlayer } from './KioskPlayer'
import { KioskSetup } from './KioskSetup'
import { sessionRecordingsKioskLogic } from './sessionRecordingsKioskLogic'

export const scene: SceneExport = {
    component: SessionRecordingsKiosk,
    logic: sessionRecordingsKioskLogic,
}

export function SessionRecordingsKiosk(): JSX.Element {
    const { isConfigured, recordingsLoading, hasRecordings } = useValues(sessionRecordingsKioskLogic)
    const { resetPlayback } = useActions(sessionRecordingsKioskLogic)

    if (!isConfigured) {
        return (
            <div className="SessionRecordingsKiosk SessionRecordingsKiosk--setup">
                <KioskSetup />
            </div>
        )
    }

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
                    <h2>No recordings found</h2>
                    <p>No recordings matched your filters. Try adjusting the date range or page filter.</p>
                    <LemonButton type="secondary" onClick={resetPlayback}>
                        Back to setup
                    </LemonButton>
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
