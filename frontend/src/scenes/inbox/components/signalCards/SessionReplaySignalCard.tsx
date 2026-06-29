import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconBug, IconCursorClick, IconGlobe, IconKeyboard, IconPlay } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'
import type { LemonTagType } from '@posthog/lemon-ui'

import { sessionRecordingInfoLogic } from 'lib/components/ViewRecordingButton/sessionRecordingInfoLogic'
import ViewRecordingButton, {
    RecordingPlayerType,
    useRecordingButton,
} from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { Dayjs, dayjs } from 'lib/dayjs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { humanFriendlyDuration, reverseColonDelimitedDuration } from 'lib/utils/durations'
import { teamLogic } from 'scenes/teamLogic'

import { getExportsContentRetrieveUrl } from '~/generated/core/api'
import type { SessionProblemEventEntry, SessionProblemSignalExtra } from '~/queries/schema/schema-signals'

import { SignalCardShell } from './SignalCardShell'
import type { SignalCardEntry, SignalCardProps } from './types'

/** How many timeline events to show before collapsing the rest behind a toggle. */
const TIMELINE_PREVIEW_COUNT = 4

const PROBLEM_TYPE_TAG: Record<SessionProblemSignalExtra['problem_type'], { label: string; type: LemonTagType }> = {
    blocking_exception: { label: 'Blocking exception', type: 'danger' },
    failure: { label: 'Failure', type: 'danger' },
    non_blocking_exception: { label: 'Exception', type: 'warning' },
    abandonment: { label: 'Abandonment', type: 'warning' },
    confusion: { label: 'Confusion', type: 'caution' },
}

/** Narrows a raw `extra` payload to the live session-problem shape. */
export function isSessionProblemExtra(
    extra: Record<string, unknown>
): extra is Record<string, unknown> & SessionProblemSignalExtra {
    return typeof extra.session_id === 'string' && 'problem_type' in extra
}

/**
 * Segment and event times arrive as recording-relative offsets (`MM:SS` / `HH:MM:SS`), not datetimes.
 * Combine the offset with the session start to get an absolute timestamp the player can seek to.
 */
function recordingSeekTime(sessionStartTime: string | undefined, offset: string | undefined): Dayjs | undefined {
    const offsetSeconds = reverseColonDelimitedDuration(offset)
    if (!sessionStartTime || offsetSeconds === null) {
        return undefined
    }
    return dayjs(sessionStartTime).add(offsetSeconds, 'second')
}

/** Picks a glyph for a timeline event based on its interaction type. */
function EventGlyph({ entry }: { entry: SessionProblemEventEntry }): JSX.Element {
    const className = 'size-3.5 shrink-0 text-tertiary'
    switch (entry.event_type) {
        case 'click':
            return <IconCursorClick className={className} aria-hidden />
        case 'keypress':
        case 'input':
            return <IconKeyboard className={className} aria-hidden />
        case 'exception':
            return <IconBug className={className} aria-hidden />
        case 'pageview':
        case '$pageview':
            return <IconGlobe className={className} aria-hidden />
        default:
            return <IconGlobe className={className} aria-hidden />
    }
}

/** A single row in the problem-event timeline; its time opens the recording at that moment. */
function TimelineRow({
    entry,
    sessionId,
    sessionStartTime,
}: {
    entry: SessionProblemEventEntry
    sessionId: string
    sessionStartTime: string | undefined
}): JSX.Element {
    const primaryText = entry.interaction_text?.trim() || entry.event
    return (
        <li className="flex items-start gap-2 py-0.5">
            <EventGlyph entry={entry} />
            <div className="flex-1 min-w-0">
                <div className="text-xs text-primary truncate">{primaryText}</div>
                {entry.current_url && (
                    <div className="text-xs text-tertiary font-mono truncate">{entry.current_url}</div>
                )}
            </div>
            <ViewRecordingButton
                sessionId={sessionId}
                timestamp={recordingSeekTime(sessionStartTime, entry.timestamp)}
                openPlayerIn={RecordingPlayerType.Modal}
                size="xsmall"
                type="tertiary"
                label={entry.timestamp}
            />
        </li>
    )
}

/** Live card for a session-replay problem segment: thumbnail preview, replay link-out, and an event timeline. */
export function SessionReplaySignalCard({ signal }: SignalCardProps): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    const [showAllEvents, setShowAllEvents] = useState(false)
    const [thumbnailFailed, setThumbnailFailed] = useState(false)

    const extra = signal.extra as Record<string, unknown> & SessionProblemSignalExtra
    const problemTag = PROBLEM_TYPE_TAG[extra.problem_type]

    const hasThumbnail = extra.exported_asset_id !== undefined && currentTeamId !== null && !thumbnailFailed
    const thumbnailSrc = hasThumbnail
        ? getExportsContentRetrieveUrl(String(currentTeamId), extra.exported_asset_id as number)
        : undefined

    const segmentSeekTime = recordingSeekTime(extra.session_start_time, extra.start_time)

    // Mirror ViewRecordingButton's `checkRecordingExists`: batch-check the recording so the play
    // affordance disables (rather than opening an empty player) when the recording wasn't captured.
    const { checkRecordingInfo } = useActions(sessionRecordingInfoLogic)
    const { getRecordingExists } = useValues(sessionRecordingInfoLogic)
    useEffect(() => {
        checkRecordingInfo(extra.session_id)
    }, [extra.session_id, checkRecordingInfo])
    const hasRecording = getRecordingExists(extra.session_id)

    const { onClick: openRecording, disabledReason } = useRecordingButton({
        sessionId: extra.session_id,
        timestamp: segmentSeekTime,
        openPlayerIn: RecordingPlayerType.Modal,
        hasRecording,
    })

    const events = extra.event_history ?? []
    const visibleEvents = showAllEvents ? events : events.slice(0, TIMELINE_PREVIEW_COUNT)

    const activeDuration =
        extra.session_active_seconds !== undefined ? humanFriendlyDuration(extra.session_active_seconds) : undefined
    const totalDuration =
        extra.session_duration !== undefined ? humanFriendlyDuration(extra.session_duration) : undefined

    return (
        <SignalCardShell
            signal={signal}
            label={extra.segment_title}
            rightSlot={
                problemTag ? (
                    <LemonTag type={problemTag.type} size="small" className="shrink-0">
                        {problemTag.label}
                    </LemonTag>
                ) : undefined
            }
        >
            {signal.content && (
                <LemonMarkdown className="text-sm text-secondary mb-2" disableImages>
                    {signal.content}
                </LemonMarkdown>
            )}

            {/* The 16:9 preview frame is itself the play affordance — clicking it opens the recording at the segment. */}
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
                        alt={`Recording preview for ${extra.segment_title}`}
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

            {/* Dot-separated meta line: affected user, segment window, active/total duration. */}
            <div className="flex items-center gap-1.5 flex-wrap text-xs text-tertiary mb-2">
                <span className="font-mono">{extra.distinct_id.slice(0, 10)}…</span>
                <span>·</span>
                <span className="font-mono">
                    {extra.start_time} – {extra.end_time}
                </span>
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

            {/* Compact problem-event timeline, collapsed past the preview count. */}
            {events.length > 0 && (
                <div className="border-t pt-2">
                    <ul className="flex flex-col">
                        {visibleEvents.map((entry, index) => (
                            <TimelineRow
                                key={`${entry.timestamp}-${index}`}
                                entry={entry}
                                sessionId={extra.session_id}
                                sessionStartTime={extra.session_start_time}
                            />
                        ))}
                    </ul>
                    {events.length > TIMELINE_PREVIEW_COUNT && (
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={() => setShowAllEvents(!showAllEvents)}
                            className="mt-1"
                        >
                            {showAllEvents ? 'Show fewer events' : `Show all ${events.length} events`}
                        </LemonButton>
                    )}
                </div>
            )}
        </SignalCardShell>
    )
}

export const sessionReplaySignalCardEntry: SignalCardEntry = {
    key: 'session_replay',
    matches: (signal) => signal.source_product === 'session_replay' && isSessionProblemExtra(signal.extra),
    Component: SessionReplaySignalCard,
}
