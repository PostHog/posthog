import { useValues } from 'kea'
import { useState } from 'react'

import { IconBug, IconCursorClick, IconExternal, IconGlobe, IconKeyboard, IconPlay } from '@posthog/icons'
import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'
import type { LemonTagType } from '@posthog/lemon-ui'

import ViewRecordingButton, { RecordingPlayerType } from 'lib/components/ViewRecordingButton/ViewRecordingButton'
import { dayjs } from 'lib/dayjs'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { humanFriendlyDetailedTime } from 'lib/utils/datetime'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

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
function TimelineRow({ entry, sessionId }: { entry: SessionProblemEventEntry; sessionId: string }): JSX.Element {
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
                timestamp={entry.timestamp}
                openPlayerIn={RecordingPlayerType.Modal}
                size="xsmall"
                type="tertiary"
                label={humanFriendlyDetailedTime(entry.timestamp)}
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

    const replayUrl = urls.replaySingle(extra.session_id, {
        unixTimestampMillis: dayjs(extra.start_time).valueOf(),
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

            {/* 16:9 framed preview: eager thumbnail when an export exists, otherwise a play affordance. */}
            <div className="relative w-full aspect-video rounded overflow-hidden border bg-surface-secondary mb-2">
                {thumbnailSrc ? (
                    <>
                        <img
                            src={thumbnailSrc}
                            alt={`Recording preview for ${extra.segment_title}`}
                            className="absolute inset-0 size-full object-cover"
                            onError={() => setThumbnailFailed(true)}
                        />
                        <div className="absolute inset-0 flex items-center justify-center bg-black/20">
                            <ViewRecordingButton
                                sessionId={extra.session_id}
                                timestamp={extra.start_time}
                                openPlayerIn={RecordingPlayerType.Modal}
                                checkRecordingExists
                                size="small"
                                type="primary"
                                label="Play"
                            />
                        </div>
                    </>
                ) : (
                    <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 text-tertiary">
                        <IconPlay className="size-6" aria-hidden />
                        <ViewRecordingButton
                            sessionId={extra.session_id}
                            timestamp={extra.start_time}
                            openPlayerIn={RecordingPlayerType.Modal}
                            checkRecordingExists
                            size="small"
                            type="secondary"
                            label="Play recording"
                        />
                    </div>
                )}
            </div>

            {/* Dot-separated meta line: affected user, segment window, active/total duration. */}
            <div className="flex items-center gap-1.5 flex-wrap text-xs text-tertiary mb-2">
                <span className="font-mono">{extra.distinct_id.slice(0, 10)}…</span>
                <span>·</span>
                <span>
                    {humanFriendlyDetailedTime(extra.start_time)} – {humanFriendlyDetailedTime(extra.end_time)}
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

            <div className="flex items-center mt-2">
                <span className="flex-1" />
                <Link to={replayUrl} className="flex items-center gap-1 text-xs font-medium shrink-0">
                    Open replay <IconExternal className="size-3" />
                </Link>
            </div>
        </SignalCardShell>
    )
}

export const sessionReplaySignalCardEntry: SignalCardEntry = {
    key: 'session_replay',
    matches: (signal) => signal.source_product === 'session_replay' && isSessionProblemExtra(signal.extra),
    Component: SessionReplaySignalCard,
}
