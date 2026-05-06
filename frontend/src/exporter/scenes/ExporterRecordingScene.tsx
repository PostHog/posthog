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
}: Pick<ExportedData, 'recording' | 'mode' | 'autoplay' | 'noBorder' | 'exportToken' | 'showInspector'>): JSX.Element {
    return (
        <SessionRecordingPlayer
            playerKey="exporter"
            sessionRecordingId={recording!.id}
            mode={mode ?? SessionRecordingPlayerMode.Sharing}
            autoPlay={autoplay ?? false}
            withSidebar={showInspector ?? false}
            noBorder={noBorder ?? false}
            accessToken={exportToken}
        />
    )
}
