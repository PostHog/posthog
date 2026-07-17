import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconPlay } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { sessionRecordingInfoLogic } from 'lib/components/ViewRecordingButton/sessionRecordingInfoLogic'
import { RecordingPlayerType, useRecordingButton } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { Dayjs, dayjs } from 'lib/dayjs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { colonDelimitedDuration, humanFriendlyDuration } from 'lib/utils/durations'
import { identifierToHuman } from 'lib/utils/strings'
import { teamLogic } from 'scenes/teamLogic'

import { getExportsContentRetrieveUrl } from '~/generated/core/api'

import type { ReplayVisionScannerFindingSignalExtraApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalCardShell } from './SignalCardShell'
import type { SignalCardEntry, SignalCardProps } from './types'

/** Narrows a raw `extra` payload to the replay-vision scanner-finding shape. */
export function isScannerFindingExtra(
    value: unknown
): value is Record<string, unknown> & ReplayVisionScannerFindingSignalExtraApi {
    if (typeof value !== 'object' || value === null) {
        return false
    }
    const extra = value as Record<string, unknown>
    return typeof extra.session_id === 'string' && typeof extra.problem_type === 'string' && 'confidence' in extra
}

/**
 * Findings carry `start_time`/`end_time` as second offsets from the recording start, and
 * `recording_start_time` as an absolute datetime. Combine them to get an instant the player can seek to.
 */
function findingSeekTime(recordingStartTime: string | null | undefined, offsetSeconds: number): Dayjs | undefined {
    if (!recordingStartTime) {
        return undefined
    }
    return dayjs(recordingStartTime).add(offsetSeconds, 'second')
}

/** Live card for a replay-vision scanner finding: thumbnail preview and a play affordance that seeks to the observation. */
export function ScannerFindingSignalCard({ signal }: SignalCardProps): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const [thumbnailFailed, setThumbnailFailed] = useState(false)

    const extra = signal.extra as Record<string, unknown> & ReplayVisionScannerFindingSignalExtraApi

    const hasThumbnail = currentTeamId !== null && !thumbnailFailed
    const thumbnailSrc = hasThumbnail
        ? getExportsContentRetrieveUrl(String(currentTeamId), extra.exported_asset_id)
        : undefined

    const findingSeek = findingSeekTime(extra.recording_start_time, extra.start_time)

    // Batch-check the recording so the play affordance disables (rather than opening an empty player)
    // when the recording wasn't captured or has expired.
    const { checkRecordingInfo } = useActions(sessionRecordingInfoLogic)
    const { getRecordingExists } = useValues(sessionRecordingInfoLogic)
    useEffect(() => {
        checkRecordingInfo(extra.session_id)
    }, [extra.session_id, checkRecordingInfo])
    const hasRecording = getRecordingExists(extra.session_id)

    const { onClick: openRecording, disabledReason } = useRecordingButton({
        sessionId: extra.session_id,
        timestamp: findingSeek,
        openPlayerIn: RecordingPlayerType.Modal,
        hasRecording,
    })

    const confidencePct = Math.round(extra.confidence * 100)

    const activeDuration =
        extra.recording_active_seconds != null ? humanFriendlyDuration(extra.recording_active_seconds) : undefined
    const totalDuration =
        extra.recording_duration != null ? humanFriendlyDuration(extra.recording_duration) : undefined

    const window = `${colonDelimitedDuration(extra.start_time, 2)} – ${colonDelimitedDuration(extra.end_time, 2)}`

    return (
        <SignalCardShell
            signal={signal}
            label={extra.scanner_name}
            rightSlot={
                <div className="flex items-center gap-1 shrink-0">
                    <LemonTag type="caution" size="small">
                        {identifierToHuman(extra.problem_type)}
                    </LemonTag>
                    <LemonTag type="muted" size="small">
                        {confidencePct}% confidence
                    </LemonTag>
                </div>
            }
        >
            {signal.content && (
                <LemonMarkdown className="text-sm text-secondary mb-2" disableImages>
                    {signal.content}
                </LemonMarkdown>
            )}

            {/* The 16:9 preview frame is itself the play affordance — clicking it opens the recording at the finding. */}
            <button
                type="button"
                onClick={openRecording}
                disabled={!!disabledReason}
                title={typeof disabledReason === 'string' ? disabledReason : undefined}
                aria-label="Play recording"
                className="group relative w-full aspect-video rounded overflow-hidden border bg-surface-secondary mb-2 cursor-pointer disabled:cursor-default disabled:opacity-70"
            >
                {thumbnailSrc && (
                    <img
                        src={thumbnailSrc}
                        alt={`Recording preview for ${extra.scanner_name}`}
                        className="absolute inset-0 size-full object-cover"
                        onError={() => setThumbnailFailed(true)}
                    />
                )}
                <div
                    className={clsx(
                        'absolute inset-0 flex items-center justify-center transition-colors',
                        thumbnailSrc ? 'bg-black/20 group-hover:bg-black/30' : 'group-hover:bg-fill-highlight-100'
                    )}
                >
                    <IconPlay
                        className={clsx('size-10 drop-shadow', thumbnailSrc ? 'text-white' : 'text-tertiary')}
                        aria-hidden
                    />
                </div>
            </button>

            {/* Dot-separated meta line: affected user, finding window, active/total duration. */}
            <div className="flex items-center gap-1.5 flex-wrap text-xs text-tertiary">
                {extra.distinct_id && (
                    <>
                        <span className="font-mono">{extra.distinct_id.slice(0, 10)}…</span>
                        <span>·</span>
                    </>
                )}
                <span className="font-mono">{window}</span>
                {(activeDuration || totalDuration) && (
                    <>
                        <span>·</span>
                        <span>
                            {activeDuration ? `${activeDuration} active` : null}
                            {activeDuration && totalDuration ? ' / ' : null}
                            {totalDuration ? `${totalDuration} total` : null}
                        </span>
                    </>
                )}
            </div>
        </SignalCardShell>
    )
}

export const scannerFindingSignalCardEntry: SignalCardEntry = {
    key: 'replay_vision',
    matches: (signal) => signal.source_product === 'replay_vision' && isScannerFindingExtra(signal.extra),
    Component: ScannerFindingSignalCard,
}
