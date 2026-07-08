import 'scenes/session-recordings/playlist/SessionRecordingPreview.scss'
import { SessionRecordingPreview } from 'scenes/session-recordings/playlist/SessionRecordingPreview'

import { sessionReplaySampleRecordings } from '../../components/WidgetCard/widgetOverviewStoryFixtures'

const PREVIEW_ORDER = 'start_time' as const

export function SessionReplayWidgetPreview(): JSX.Element {
    return (
        <div className="flex flex-col shadow-sm">
            {sessionReplaySampleRecordings.map((recording) => (
                <div key={recording.id} className="border-b">
                    <SessionRecordingPreview recording={recording} order={PREVIEW_ORDER} />
                </div>
            ))}
        </div>
    )
}
