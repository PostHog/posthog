import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { ExportedData } from '../types'

export default function ExporterRecordingScene({
    recording,
    mode,
    autoplay,
    noBorder,
    exportToken,
    showInspector,
}: {
    recording: NonNullable<ExportedData['recording']>
    mode: ExportedData['mode']
    autoplay: ExportedData['autoplay']
    noBorder: ExportedData['noBorder']
    exportToken: ExportedData['exportToken']
    showInspector: ExportedData['showInspector']
}): JSX.Element {
    return (
        <SessionRecordingPlayer
            playerKey="exporter"
            sessionRecordingId={recording.id}
            mode={mode ?? SessionRecordingPlayerMode.Sharing}
            // A shared recording link carries no autoplay field, and those pages play on open.
            autoPlay={autoplay ?? true}
            withSidebar={showInspector ?? false}
            noBorder={noBorder ?? false}
            accessToken={exportToken}
        />
    )
}
