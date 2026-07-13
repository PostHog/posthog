import { useActions, useValues } from 'kea'

import { IconRewindPlay } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { colonDelimitedDuration } from 'lib/utils/durations'

import { heatmapRecordingFallbackLogic } from './heatmapRecordingFallbackLogic'

export function HeatmapRecordingFallback({ url }: { url: string }): JSX.Element | null {
    const logic = heatmapRecordingFallbackLogic({ url })
    const { matchingRecordings } = useValues(logic)
    const { openRecording } = useActions(logic)

    if (!matchingRecordings?.length) {
        return null
    }

    return (
        <LemonBanner type="info">
            <div className="flex flex-col gap-2">
                <p className="mb-0">
                    We found recent recordings of sessions that visited this page. You can build the heatmap from a
                    recording instead: open one, scrub to the page you want as the background, then choose "View
                    heatmap" in the player.
                </p>
                <div className="flex flex-wrap gap-2">
                    {matchingRecordings.map((recording) => (
                        <LemonButton
                            key={recording.id}
                            data-attr="heatmap-recording-fallback-open-recording"
                            type="secondary"
                            size="small"
                            icon={<IconRewindPlay />}
                            onClick={() => openRecording(recording.id)}
                        >
                            <span className="flex items-center gap-1">
                                <TZLabel time={recording.start_time} />
                                {recording.recording_duration ? (
                                    <span className="text-muted">
                                        · {colonDelimitedDuration(recording.recording_duration)}
                                    </span>
                                ) : null}
                            </span>
                        </LemonButton>
                    ))}
                </div>
            </div>
        </LemonBanner>
    )
}
