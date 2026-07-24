import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useRef } from 'react'

import { IconCollapse, IconExpand, IconExternal, IconInfo, IconMinus, IconWarning } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { colonDelimitedDuration } from 'lib/utils/durations'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import {
    type ExperimentSessionContextItemApi,
    type ExperimentSessionMetricHitApi,
    type ExperimentSessionMetricSourceHitApi,
    SourceRoleEnumApi,
} from 'products/experiments/frontend/generated/api.schemas'

import {
    isControlVariant,
    sessionRecordingExperimentContextLogic,
} from '../player-meta/sessionRecordingExperimentContextLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'

function variantTooltip(item: ExperimentSessionContextItemApi): string {
    return item.multiple_variants
        ? `This session saw multiple variants (${item.variants_seen.join(', ')}) of ${item.experiment_name}. The experiment analysis counts exposure per person, which can differ from a single session.`
        : `This session saw variant "${item.variant}" of ${item.experiment_name}. The experiment analysis counts exposure per person, which can differ from a single session.`
}

function VariantTag({ item }: { item: ExperimentSessionContextItemApi }): JSX.Element | null {
    // Metric-only sessions (a future backend addition) carry no variant — render no tag rather
    // than an empty one.
    if (!item.variant && item.variants_seen.length === 0) {
        return null
    }
    const type: LemonTagType = item.multiple_variants ? 'warning' : isControlVariant(item) ? 'muted' : 'highlight'
    return (
        <Tooltip title={variantTooltip(item)}>
            <LemonTag type={type} icon={item.multiple_variants ? <IconWarning /> : undefined} className="shrink-0">
                {item.multiple_variants ? `${item.variants_seen.length} variants` : item.variant}
            </LemonTag>
        </Tooltip>
    )
}

// A busy metric can carry up to the API's 50-event cap; rendering them all inline floods the narrow
// sidebar. Show a sample of seek points and note the rest as a static count (no inline expansion —
// the full picture lives on the recordings tab's metric filter and the experiment's own analysis).
const MAX_INLINE_METRIC_EVENTS = 15

function MetricEventChips({
    seekPoints,
    onSeek,
}: {
    seekPoints: { ms: number; offsetSeconds: number }[]
    onSeek: (timestampMs: number) => void
}): JSX.Element {
    const shown = seekPoints.slice(0, MAX_INLINE_METRIC_EVENTS)
    const hiddenCount = seekPoints.length - shown.length
    return (
        <div className="flex flex-row flex-wrap gap-1 pl-3">
            {shown.map(({ ms, offsetSeconds }) => (
                <Link
                    key={ms}
                    className="font-mono tabular-nums"
                    title="Jump to this event"
                    onClick={() => onSeek(ms)}
                    data-attr="replay-experiment-context-jump-to-metric-event"
                >
                    {colonDelimitedDuration(offsetSeconds, 2)}
                </Link>
            ))}
            {hiddenCount > 0 ? <span className="text-muted">+{hiddenCount} more</span> : null}
        </div>
    )
}

// What each source is to its metric. A metric's own name says nothing about which side of it fired,
// and for most metric types that distinction is the difference between "they converted" and "they
// took the first step" — so it's spelled out rather than left to the reader.
function sourceLabel(source: ExperimentSessionMetricSourceHitApi): string | null {
    switch (source.source_role) {
        case SourceRoleEnumApi.Step:
            return source.source_total > 1
                ? `Step ${source.source_index + 1} of ${source.source_total}`
                : // A one-step funnel is just its event; the step number would be noise.
                  null
        case SourceRoleEnumApi.Numerator:
            return 'Numerator'
        case SourceRoleEnumApi.Denominator:
            return 'Denominator'
        case SourceRoleEnumApi.RetentionStart:
            return 'Start event'
        case SourceRoleEnumApi.RetentionCompletion:
            return 'Return event'
        default:
            return null
    }
}

const SESSION_SCOPE_CAVEAT =
    "What this session saw, and the metric events that fired in it. These are events a metric counts, not its result: whether they count for this person depends on their exposure and the metric's window, which the experiment analysis decides across all their sessions."

function MetricSourceRow({
    source,
    recordingStartMs,
    isWithinRecording,
    onSeek,
}: {
    source: ExperimentSessionMetricSourceHitApi
    recordingStartMs: number | null
    isWithinRecording: (timestampMs: number | null) => timestampMs is number
    onSeek: (timestampMs: number) => void
}): JSX.Element {
    // Only in-bounds occurrences are seekable — the backend's ±1h slack can place some outside the
    // playable recording. Each becomes a chip labelled with its offset from the recording start.
    const seekPoints = source.timestamps
        .map((timestamp) => dayjs(timestamp).valueOf())
        .filter((ms): ms is number => isWithinRecording(ms))
        .map((ms) => ({ ms, offsetSeconds: recordingStartMs != null ? Math.floor((ms - recordingStartMs) / 1000) : 0 }))
    const label = sourceLabel(source)

    return (
        <div className="flex flex-col gap-y-0.5 min-w-0">
            {label ? (
                <span className="pl-3 truncate text-muted">
                    {label} · {source.source_name}
                </span>
            ) : null}
            {seekPoints.length === 0 ? (
                <span className="pl-3 text-muted">Fired outside the recording</span>
            ) : (
                <MetricEventChips seekPoints={seekPoints} onSeek={onSeek} />
            )}
        </div>
    )
}

function MetricHitRow({
    hit,
    recordingStartMs,
    isWithinRecording,
    onSeek,
}: {
    hit: ExperimentSessionMetricHitApi
    recordingStartMs: number | null
    isWithinRecording: (timestampMs: number | null) => timestampMs is number
    onSeek: (timestampMs: number) => void
}): JSX.Element {
    // Metrics past the scan's aggregate ceiling carry no breakdown; their own totals are then the
    // only thing to show, unqualified — which is exactly what the 'source' role renders.
    const sources: ExperimentSessionMetricSourceHitApi[] =
        hit.sources.length > 0
            ? hit.sources
            : [
                  {
                      source_role: SourceRoleEnumApi.Source,
                      source_name: hit.metric_name,
                      source_index: 0,
                      source_total: 1,
                      event_count: hit.event_count,
                      first_timestamp: hit.first_timestamp,
                      timestamps: hit.timestamps,
                  },
              ]

    return (
        // Indented to start under the exposure-time column, so the block reads as belonging to the
        // experiment row above it rather than as another top-level row.
        <div className="flex flex-col gap-y-0.5 min-w-0 pl-8 text-xs">
            <span className="truncate">{hit.metric_name}</span>
            {sources.map((source) => (
                <MetricSourceRow
                    key={`${source.source_role}-${source.source_index}`}
                    source={source}
                    recordingStartMs={recordingStartMs}
                    isWithinRecording={isWithinRecording}
                    onSeek={onSeek}
                />
            ))}
        </div>
    )
}

function OpenExperimentButton({ item }: { item: ExperimentSessionContextItemApi }): JSX.Element {
    return (
        <LemonButton
            size="xsmall"
            type="tertiary"
            icon={<IconExternal />}
            to={urls.experiment(item.experiment_id)}
            targetBlank
            hideExternalLinkIcon
            className="shrink-0"
            tooltip="Open experiment in a new tab"
            data-attr="replay-experiment-context-experiment-link"
            onClick={() => {
                void addProductIntentForCrossSell({
                    from: ProductKey.SESSION_REPLAY,
                    to: ProductKey.EXPERIMENTS,
                    intent_context: ProductIntentContext.SESSION_REPLAY_EXPERIMENT_LINK_CLICKED,
                    metadata: { experiment_id: item.experiment_id },
                })
            }}
        />
    )
}

const OUT_OF_WINDOW_TOOLTIP =
    "The exposure was captured just outside this recording's playable range, so there's no moment to jump to."

// The person's counted first exposure may lie in an earlier session (the experiment analysis counts
// exposure per person across the whole run window), so an in-session metric event can precede this one.
const EXPOSURE_CAVEAT =
    'They may have been enrolled in an earlier session, so metric events can fire before this moment.'

function ExposureTime({
    timeInRecording,
    onSeek,
    outOfWindow,
}: {
    timeInRecording: number
    onSeek?: () => void
    outOfWindow?: boolean
}): JSX.Element {
    const label = colonDelimitedDuration(Math.max(0, timeInRecording) / 1000, null)
    if (onSeek) {
        return (
            <Tooltip title={`Jump to the first exposure in this session. ${EXPOSURE_CAVEAT}`}>
                <Link
                    className="text-xs tabular-nums shrink-0 min-w-10 text-right"
                    onClick={onSeek}
                    data-attr="replay-experiment-context-jump-to-first-exposure"
                >
                    {label}
                </Link>
            </Tooltip>
        )
    }
    return (
        <Tooltip title={outOfWindow ? OUT_OF_WINDOW_TOOLTIP : `First exposure in this session. ${EXPOSURE_CAVEAT}`}>
            <span className="text-secondary text-xs tabular-nums shrink-0 min-w-10 text-right">{label}</span>
        </Tooltip>
    )
}

function ExperimentContextRow({
    item,
    onSeek,
    outOfWindow,
    timeInRecording,
    leading,
}: {
    item: ExperimentSessionContextItemApi
    onSeek?: () => void
    outOfWindow?: boolean
    timeInRecording?: number | null
    // Leading slot rendered before the timestamp — the metric-events expand toggle, or a same-width
    // spacer so the timestamp and name columns line up across rows.
    leading?: JSX.Element | null
}): JSX.Element {
    // The name is a plain label in its own flex-1 truncate box (keeping the variant tag and
    // open-experiment icon right-aligned). Seeking lives on the timestamp; opening the experiment on
    // the icon — so the name identifies the row rather than pretending to be a control.
    return (
        <div className="flex flex-row items-center gap-x-2 min-w-0">
            {leading}
            {timeInRecording != null ? (
                <ExposureTime timeInRecording={timeInRecording} onSeek={onSeek} outOfWindow={outOfWindow} />
            ) : null}
            <div className="flex-1 min-w-0 truncate">{item.experiment_name}</div>
            <VariantTag item={item} />
            <OpenExperimentButton item={item} />
        </div>
    )
}

// The experiments scene keeps /experiments/<numeric id> in the path even while the player is embedded
// in its recordings tab, so the experiment the viewer came from is recoverable from the route. Returns
// null off that scene (the generic replay page), where there's no experiment to pin.
function experimentIdFromPath(pathname: string): number | null {
    const match = pathname.match(/\/experiments\/(\d+)/)
    return match ? Number(match[1]) : null
}

export function PlayerSidebarExperimentsSection(): JSX.Element | null {
    const { logicProps, sessionPlayerData } = useValues(sessionRecordingPlayerLogic)
    const { seekToTimestamp } = useActions(sessionRecordingPlayerLogic)
    const experimentContextLogic = sessionRecordingExperimentContextLogic({
        sessionRecordingId: logicProps.sessionRecordingId,
    })
    const { seenItems, enrolledItems, hasExperimentContext, expandedExperimentIds, experimentContextLoading } =
        useValues(experimentContextLogic)
    const { setExperimentExpanded } = useActions(experimentContextLogic)
    const { location } = useValues(router)

    // The experiment the viewer arrived from: their recordings tab keeps the URL on /experiments/<id>
    // while the player is embedded, so we can pin it and default-expand its metrics. Null on the
    // generic replay page, where there's no experiment context.
    const currentExperimentId = experimentIdFromPath(location.pathname)
    const currentItem =
        currentExperimentId != null
            ? ([...seenItems, ...enrolledItems].find((item) => item.experiment_id === currentExperimentId) ?? null)
            : null

    // Default-expand the current experiment's metrics on load so they're visible right away — but only
    // once per experiment. Auto-expanding again on a later metric-count change (e.g. a context refetch)
    // would silently reopen a row the viewer deliberately collapsed, so a ref tracks who's been done.
    const currentExpandableId = currentItem?.experiment_id
    const currentMetricCount = currentItem?.metrics_in_session.length ?? 0
    const autoExpandedIds = useRef<Set<number>>(new Set())
    useEffect(() => {
        if (
            currentExpandableId != null &&
            currentMetricCount > 0 &&
            !autoExpandedIds.current.has(currentExpandableId)
        ) {
            autoExpandedIds.current.add(currentExpandableId)
            setExperimentExpanded(currentExpandableId, true)
        }
    }, [currentExpandableId, currentMetricCount, setExperimentExpanded])

    if (experimentContextLoading && !hasExperimentContext) {
        if (currentExperimentId == null) {
            return null
        }
        return (
            <div
                className="rounded border bg-surface-primary px-2 py-1 flex flex-col gap-y-1"
                data-attr="replay-experiment-context-overview-loading"
            >
                <h4 className="font-semibold text-xs mb-0">Experiments</h4>
                <LemonSkeleton className="h-4 w-2/3" />
                <LemonSkeleton className="h-4 w-1/2" />
            </div>
        )
    }

    if (!hasExperimentContext) {
        return null
    }

    const recordingStartMs = sessionPlayerData?.start?.valueOf() ?? null
    const recordingEndMs =
        recordingStartMs != null && sessionPlayerData?.durationMs != null
            ? recordingStartMs + sessionPlayerData.durationMs
            : null
    // The backend can return timestamps from its ±1h slack around the recording; seeking to an
    // out-of-bounds time silently clamps to a boundary, so only offer jumps for moments that fall
    // inside the playable recording.
    const isWithinRecording = (timestampMs: number | null): timestampMs is number =>
        timestampMs != null &&
        recordingStartMs != null &&
        recordingEndMs != null &&
        timestampMs >= recordingStartMs &&
        timestampMs <= recordingEndMs

    // Reserve a leading gutter on every seen row (so timestamps and names align) only when at least
    // one experiment has an expand toggle; with nothing expandable, keep the list flush-left.
    const anySeenExpandable = seenItems.some((seenItem) => seenItem.metrics_in_session.length > 0)

    // One seen experiment rendered in full: its timestamp seek control, the expand toggle (or the
    // no-metrics marker), and — when expanded — its metric hits. Extracted so the pinned "current"
    // experiment reuses the exact same treatment as the list rows below it.
    const renderSeenRow = (item: ExperimentSessionContextItemApi): JSX.Element => {
        const exposedAtMs = item.first_exposure_timestamp ? dayjs(item.first_exposure_timestamp).valueOf() : null
        const canSeek = isWithinRecording(exposedAtMs)
        // Distinguish "seen but outside the window" (worth a tooltip) from "bounds not known yet"
        // (transient, no tooltip) so we never explain a non-jump we can't actually vouch for.
        const outOfWindow =
            exposedAtMs != null &&
            recordingStartMs != null &&
            recordingEndMs != null &&
            (exposedAtMs < recordingStartMs || exposedAtMs > recordingEndMs)
        const hasMetrics = item.metrics_in_session.length > 0
        const isExpanded = expandedExperimentIds.includes(item.experiment_id)
        return (
            <div key={item.experiment_id} className="flex flex-col gap-y-0.5 min-w-0">
                <ExperimentContextRow
                    item={item}
                    onSeek={canSeek && exposedAtMs != null ? () => seekToTimestamp(exposedAtMs) : undefined}
                    outOfWindow={outOfWindow}
                    timeInRecording={
                        exposedAtMs != null && recordingStartMs != null ? exposedAtMs - recordingStartMs : null
                    }
                    leading={
                        // -me-1.5 pulls the timestamp back toward the toggle so the icon and time read
                        // as one column (and line up better with the expanded metrics), without
                        // tightening the timestamp-to-name gap.
                        anySeenExpandable ? (
                            <div className="shrink-0 flex w-[1.625rem] items-center justify-center -me-1.5">
                                {hasMetrics ? (
                                    <LemonButton
                                        size="xsmall"
                                        icon={isExpanded ? <IconCollapse /> : <IconExpand />}
                                        onClick={() => setExperimentExpanded(item.experiment_id, !isExpanded)}
                                        tooltip={
                                            isExpanded
                                                ? 'Hide metric events'
                                                : `Show metric events (${item.metrics_in_session.length})`
                                        }
                                        data-attr="replay-experiment-context-expand-metrics"
                                    />
                                ) : (
                                    // Same component and size as the expand button so the marker has an
                                    // identical box, border, and tooltip hover target. disabledReason keeps
                                    // it hoverable (LemonButton disables via aria-disabled, not the native
                                    // attribute) while signalling there's nothing to expand.
                                    <LemonButton
                                        size="xsmall"
                                        icon={<IconMinus />}
                                        disabledReason="No experiment metric fired in this session"
                                        data-attr="replay-experiment-context-no-metrics"
                                    />
                                )}
                            </div>
                        ) : undefined
                    }
                />
                {isExpanded && hasMetrics ? (
                    <div className="flex flex-col gap-y-0.5">
                        {item.metrics_in_session.map((hit) => (
                            <MetricHitRow
                                key={hit.metric_uuid}
                                hit={hit}
                                recordingStartMs={recordingStartMs}
                                isWithinRecording={isWithinRecording}
                                onSeek={seekToTimestamp}
                            />
                        ))}
                    </div>
                ) : null}
            </div>
        )
    }

    const otherSeenItems = currentItem
        ? seenItems.filter((item) => item.experiment_id !== currentItem.experiment_id)
        : seenItems
    const otherEnrolledItems = currentItem
        ? enrolledItems.filter((item) => item.experiment_id !== currentItem.experiment_id)
        : enrolledItems
    // Pin the current experiment only when there are other experiments to stand out from — a lone
    // "Viewing" row is just clutter. Otherwise it stays inline in the normal lists below.
    const pinnedItem = currentItem && (otherSeenItems.length > 0 || otherEnrolledItems.length > 0) ? currentItem : null
    const listSeenItems = pinnedItem ? otherSeenItems : seenItems
    const listEnrolledItems = pinnedItem ? otherEnrolledItems : enrolledItems

    return (
        <div
            className="rounded border bg-surface-primary px-2 py-1 flex flex-col gap-y-1"
            data-attr="replay-experiment-context-overview"
        >
            <h4 className="font-semibold text-xs mb-0 flex items-center gap-1">
                Experiments
                {/* One icon for the whole section: the caveat applies to every row and every metric
                    under it, so repeating it per metric name would fire a tooltip on almost any
                    hover in here. */}
                <Tooltip title={SESSION_SCOPE_CAVEAT}>
                    <IconInfo className="size-3 shrink-0 text-secondary" />
                </Tooltip>
            </h4>

            {pinnedItem ? (
                <div className="flex flex-col gap-y-0.5" data-attr="replay-experiment-context-current">
                    <span className="text-[0.625rem] font-semibold uppercase tracking-wider text-secondary">
                        Viewing
                    </span>
                    {pinnedItem.first_exposure_timestamp != null ? (
                        renderSeenRow(pinnedItem)
                    ) : (
                        <ExperimentContextRow item={pinnedItem} />
                    )}
                </div>
            ) : null}

            {pinnedItem && listSeenItems.length > 0 ? (
                <span className="text-[0.625rem] font-semibold uppercase tracking-wider text-muted">
                    Other experiments in this session
                </span>
            ) : null}

            {listSeenItems.map((item) => renderSeenRow(item))}

            {listEnrolledItems.length > 0 ? (
                <LemonCollapse
                    embedded
                    size="small"
                    panels={[
                        {
                            key: 'enrolled',
                            header: `Also enrolled, not exposed in this session (${listEnrolledItems.length})`,
                            content: (
                                <div className="flex flex-col gap-y-1">
                                    {listEnrolledItems.map((item) => (
                                        <ExperimentContextRow key={item.experiment_id} item={item} />
                                    ))}
                                </div>
                            ),
                        },
                    ]}
                />
            ) : null}
        </div>
    )
}
