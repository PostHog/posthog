import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { SessionRecordingPlayerMode } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { ExportedData } from '../types'

// Image exports render a single frame in a headless, memory-constrained browser. A recording whose
// keyframes are sparse near the seeked offset would otherwise make rrweb load the whole session into the
// DOM and OOM the renderer (surfaces as BrowserlessUnavailable "page has been closed"). Cap how many
// snapshot sources a seek loads so the export renders a best-effort frame instead of dying. Higher
// recovers more keyframe-poor recordings at the cost of renderer memory.
const EXPORTER_MAX_SEEK_FILL_SOURCES = 150

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
            autoPlay={autoplay ?? false}
            withSidebar={showInspector ?? false}
            noBorder={noBorder ?? false}
            accessToken={exportToken}
            maxSeekFillSources={EXPORTER_MAX_SEEK_FILL_SOURCES}
        />
    )
}
