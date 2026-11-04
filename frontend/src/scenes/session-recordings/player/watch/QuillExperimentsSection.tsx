import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useRef } from 'react'

import { IconCollapse, IconExpand, IconExternal, IconInfo, IconMinus, IconWarning } from '@posthog/icons'
import {
    Badge,
    Button,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    Skeleton,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { colonDelimitedDuration, humanFriendlyDuration } from 'lib/utils/durations'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { computeExposureSeek } from 'scenes/session-recordings/player/sidebar/PlayerSidebarExperimentsSection'
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

const MAX_INLINE_METRIC_EVENTS = 15

const SESSION_SCOPE_CAVEAT =
    "What this session saw, and the metric events that fired in it. These are events a metric counts, not its result: whether they count for this person depends on their exposure and the metric's window, which the experiment analysis decides across all their sessions."

const EXPOSURE_CAVEAT =
    'They may have been enrolled in an earlier session, so metric events can fire before this moment.'

const NOT_EXPOSED_CAVEAT =
    "The flag was active in this session, but no exposure event was captured here, so this session isn't where the experiment analysis counted this person's exposure."

function Hover({ tooltip, children }: { tooltip: React.ReactNode; children: JSX.Element }): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger render={<span className="contents" />}>{children}</TooltipTrigger>
            <TooltipContent className="max-w-80">{tooltip}</TooltipContent>
        </Tooltip>
    )
}

function variantTooltip(item: ExperimentSessionContextItemApi): string {
    return item.multiple_variants
        ? `This session saw multiple variants (${item.variants_seen.join(', ')}) of ${item.experiment_name}. The experiment analysis counts exposure per person, which can differ from a single session.`
        : `This session saw variant "${item.variant}" of ${item.experiment_name}. The experiment analysis counts exposure per person, which can differ from a single session.`
}

function VariantTag({ item }: { item: ExperimentSessionContextItemApi }): JSX.Element | null {
    if (!item.variant && item.variants_seen.length === 0) {
        return null
    }
    return (
        <Hover tooltip={variantTooltip(item)}>
            <Badge
                variant={item.multiple_variants ? 'warning' : isControlVariant(item) ? 'default' : 'info'}
                className="shrink-0 gap-1"
            >
                {item.multiple_variants && <IconWarning />}
                {item.multiple_variants ? `${item.variants_seen.length} variants` : item.variant}
            </Badge>
        </Hover>
    )
}

function SeekLink({
    label,
    tooltip,
    className,
    onSeek,
    dataAttr,
}: {
    label: string
    tooltip?: string
    className?: string
    onSeek: () => void
    dataAttr: string
}): JSX.Element {
    const button = (
        <Button variant="link" size="inline" className={className} onClick={onSeek} data-attr={dataAttr}>
            {label}
        </Button>
    )
    return tooltip ? <Hover tooltip={tooltip}>{button}</Hover> : button
}

// A busy metric can carry up to the API's 50-event cap; a sample of seek points keeps the panel readable.
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
                <SeekLink
                    key={ms}
                    label={colonDelimitedDuration(offsetSeconds, 2)}
                    tooltip="Jump to this event"
                    className="font-mono tabular-nums"
                    onSeek={() => onSeek(ms)}
                    dataAttr="replay-experiment-context-jump-to-metric-event"
                />
            ))}
            {hiddenCount > 0 ? <span className="text-muted-foreground">+{hiddenCount} more</span> : null}
        </div>
    )
}

// Which side of its metric a source is, since that is the difference between "converted" and "took the first step".
function sourceLabel(source: ExperimentSessionMetricSourceHitApi): string | null {
    switch (source.source_role) {
        case SourceRoleEnumApi.Step:
            return source.source_total > 1 ? `Step ${source.source_index + 1} of ${source.source_total}` : null
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
    // Only in-bounds occurrences are seekable: the backend's slack can place some outside the playable recording.
    const seekPoints = source.timestamps
        .map((timestamp) => dayjs(timestamp).valueOf())
        .filter((ms): ms is number => isWithinRecording(ms))
        .map((ms) => ({ ms, offsetSeconds: recordingStartMs != null ? Math.floor((ms - recordingStartMs) / 1000) : 0 }))
    const label = sourceLabel(source)

    return (
        <div className="flex flex-col gap-y-0.5 min-w-0">
            {label ? (
                <span className="pl-3 truncate text-muted-foreground">
                    {label} · {source.source_name}
                </span>
            ) : null}
            {seekPoints.length === 0 ? (
                <span className="pl-3 text-muted-foreground">Fired outside the recording</span>
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
    // Metrics past the scan's aggregate ceiling carry no breakdown, so their own totals render as the one source.
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
        <Button
            size="icon-xs"
            className="shrink-0"
            tooltip="Open experiment in a new tab"
            aria-label="Open experiment in a new tab"
            render={<LinkPrimitive to={urls.experiment(item.experiment_id)} target="_blank" />}
            data-attr="replay-experiment-context-experiment-link"
            onClick={() => {
                void addProductIntentForCrossSell({
                    from: ProductKey.SESSION_REPLAY,
                    to: ProductKey.EXPERIMENTS,
                    intent_context: ProductIntentContext.SESSION_REPLAY_EXPERIMENT_LINK_CLICKED,
                    metadata: { experiment_id: item.experiment_id },
                })
            }}
        >
            <IconExternal />
        </Button>
    )
}

interface ExposureTimeProps {
    offsetMs: number
    placement: 'before' | 'inside' | 'after'
    onSeek: () => void
}

// The label carries the signed offset so an out-of-window exposure reads as real, not as 00:00.
function ExposureTime({ offsetMs, placement, onSeek }: ExposureTimeProps): JSX.Element {
    // An in-window offset floors to match the player clock; an out-of-window gap rounds up so it never prints 00:00.
    const seconds = placement === 'inside' ? Math.floor(offsetMs / 1000) : Math.ceil(Math.abs(offsetMs) / 1000)
    const magnitude = colonDelimitedDuration(seconds, null)
    const label = placement === 'before' ? `-${magnitude}` : placement === 'after' ? `+${magnitude}` : magnitude
    const gap = humanFriendlyDuration(seconds)
    const tooltip =
        placement === 'before'
            ? `The exposure fired ${gap} before the replay begins. Jumps to the first frame.`
            : placement === 'after'
              ? `The exposure fired ${gap} after the replay ends. Jumps to the last frame.`
              : `Jump to the first exposure in this session. ${EXPOSURE_CAVEAT}`
    return (
        <SeekLink
            label={label}
            tooltip={tooltip}
            className="text-xs tabular-nums shrink-0 min-w-10 justify-end"
            onSeek={onSeek}
            dataAttr="replay-experiment-context-jump-to-first-exposure"
        />
    )
}

function NotExposedInSessionLabel({ children, className }: { children: string; className?: string }): JSX.Element {
    return (
        <Hover tooltip={NOT_EXPOSED_CAVEAT}>
            <span className={className} data-attr="replay-experiment-context-not-exposed">
                {children}
                <IconInfo className="inline-block ml-1 size-3 text-muted-foreground" />
            </span>
        </Hover>
    )
}

function ExperimentContextRow({
    item,
    exposure,
    leading,
}: {
    item: ExperimentSessionContextItemApi
    exposure?: ExposureTimeProps | null
    leading?: JSX.Element | null
}): JSX.Element {
    return (
        <div className="flex flex-row items-center gap-x-2 min-w-0">
            {leading}
            {exposure ? <ExposureTime {...exposure} /> : null}
            <div className="flex-1 min-w-0 truncate">{item.experiment_name}</div>
            <VariantTag item={item} />
            <OpenExperimentButton item={item} />
        </div>
    )
}

// The experiments scene keeps /experiments/<id> in the path while the player is embedded in its recordings tab.
function experimentIdFromPath(pathname: string): number | null {
    const match = pathname.match(/\/experiments\/(\d+)/)
    return match ? Number(match[1]) : null
}

function GroupLabel({ children, muted = false }: { children: string; muted?: boolean }): JSX.Element {
    return (
        <span
            className={`text-[0.625rem] font-semibold uppercase tracking-wider ${muted ? 'text-muted-foreground' : 'text-foreground'}`}
        >
            {children}
        </span>
    )
}

export function QuillExperimentsSection(): JSX.Element | null {
    const { logicProps, sessionPlayerData } = useValues(sessionRecordingPlayerLogic)
    const { seekToTime } = useActions(sessionRecordingPlayerLogic)
    const experimentContextLogic = sessionRecordingExperimentContextLogic({
        sessionRecordingId: logicProps.sessionRecordingId,
    })
    const { seenItems, enrolledItems, hasExperimentContext, expandedExperimentIds, experimentContextLoading } =
        useValues(experimentContextLogic)
    const { setExperimentExpanded } = useActions(experimentContextLogic)
    const { location } = useValues(router)

    const currentExperimentId = experimentIdFromPath(location.pathname)
    const currentItem =
        currentExperimentId != null
            ? ([...seenItems, ...enrolledItems].find((item) => item.experiment_id === currentExperimentId) ?? null)
            : null

    // Default-expand the current experiment's metrics once; a later refetch must not reopen a row the viewer closed.
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
                className="rounded border border-border bg-card px-2 py-1 flex flex-col gap-y-1"
                data-attr="replay-experiment-context-overview-loading"
            >
                <h4 className="font-semibold text-xs mb-0">Experiments</h4>
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-4 w-1/2" />
            </div>
        )
    }

    if (!hasExperimentContext) {
        return null
    }

    const recordingStartMs = sessionPlayerData?.start?.valueOf() ?? null
    // seekToTime rather than seekToTimestamp, because only seekToTime consumes a pending auto-skip.
    const seekToTimestamp = (timestampMs: number): void => {
        if (recordingStartMs != null) {
            seekToTime(timestampMs - recordingStartMs)
        }
    }
    const recordingEndMs =
        recordingStartMs != null && sessionPlayerData?.durationMs != null
            ? recordingStartMs + sessionPlayerData.durationMs
            : null
    const isWithinRecording = (timestampMs: number | null): timestampMs is number =>
        timestampMs != null &&
        recordingStartMs != null &&
        recordingEndMs != null &&
        timestampMs >= recordingStartMs &&
        timestampMs <= recordingEndMs

    const anySeenExpandable = seenItems.some((seenItem) => seenItem.metrics_in_session.length > 0)

    const renderSeenRow = (item: ExperimentSessionContextItemApi): JSX.Element => {
        const exposedAtMs = item.first_exposure_timestamp ? dayjs(item.first_exposure_timestamp).valueOf() : null
        const seek =
            exposedAtMs != null && recordingStartMs != null
                ? computeExposureSeek(exposedAtMs, recordingStartMs, recordingEndMs)
                : null
        const hasMetrics = item.metrics_in_session.length > 0
        const isExpanded = expandedExperimentIds.includes(item.experiment_id)
        return (
            <div key={item.experiment_id} className="flex flex-col gap-y-0.5 min-w-0">
                <ExperimentContextRow
                    item={item}
                    exposure={
                        seek
                            ? {
                                  offsetMs: seek.offsetMs,
                                  placement: seek.placement,
                                  onSeek: () => seekToTimestamp(seek.seekTargetMs),
                              }
                            : null
                    }
                    leading={
                        anySeenExpandable ? (
                            <div className="shrink-0 flex w-[1.625rem] items-center justify-center -me-1.5">
                                {hasMetrics ? (
                                    <Button
                                        size="icon-xs"
                                        onClick={() => setExperimentExpanded(item.experiment_id, !isExpanded)}
                                        tooltip={
                                            isExpanded
                                                ? 'Hide metric events'
                                                : `Show metric events (${item.metrics_in_session.length})`
                                        }
                                        aria-label={isExpanded ? 'Hide metric events' : 'Show metric events'}
                                        data-attr="replay-experiment-context-expand-metrics"
                                    >
                                        {isExpanded ? <IconCollapse /> : <IconExpand />}
                                    </Button>
                                ) : (
                                    <Button
                                        size="icon-xs"
                                        disabledReason="No experiment metric fired in this session"
                                        aria-label="No experiment metric fired in this session"
                                        data-attr="replay-experiment-context-no-metrics"
                                    >
                                        <IconMinus />
                                    </Button>
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
    // Pin the current experiment only when there are others to stand out from.
    const pinnedItem = currentItem && (otherSeenItems.length > 0 || otherEnrolledItems.length > 0) ? currentItem : null
    const listSeenItems = pinnedItem ? otherSeenItems : seenItems
    const listEnrolledItems = pinnedItem ? otherEnrolledItems : enrolledItems

    return (
        <div
            className="rounded border border-border bg-card px-2 py-1 flex flex-col gap-y-1"
            data-attr="replay-experiment-context-overview"
        >
            <h4 className="font-semibold text-xs mb-0 flex items-center gap-1">
                Experiments
                <Hover tooltip={SESSION_SCOPE_CAVEAT}>
                    <IconInfo className="size-3 shrink-0 text-muted-foreground" />
                </Hover>
            </h4>

            {pinnedItem ? (
                <div className="flex flex-col gap-y-0.5" data-attr="replay-experiment-context-current">
                    <GroupLabel>Viewing</GroupLabel>
                    {pinnedItem.first_exposure_timestamp != null ? (
                        renderSeenRow(pinnedItem)
                    ) : (
                        <>
                            <ExperimentContextRow item={pinnedItem} />
                            <NotExposedInSessionLabel className="w-fit text-xs text-muted-foreground">
                                Not exposed in this session
                            </NotExposedInSessionLabel>
                        </>
                    )}
                </div>
            ) : null}

            {pinnedItem && listSeenItems.length > 0 ? (
                <GroupLabel muted>Other experiments in this session</GroupLabel>
            ) : null}

            {listSeenItems.map((item) => renderSeenRow(item))}

            {listEnrolledItems.length > 0 ? (
                <Collapsible>
                    <CollapsibleTrigger className="w-full text-xs">
                        <NotExposedInSessionLabel>
                            {`Also enrolled, not exposed in this session (${listEnrolledItems.length})`}
                        </NotExposedInSessionLabel>
                        <span className="grow" />
                    </CollapsibleTrigger>
                    <CollapsibleContent>
                        <div className="flex flex-col gap-y-1 pt-1">
                            {listEnrolledItems.map((item) => (
                                <ExperimentContextRow key={item.experiment_id} item={item} />
                            ))}
                        </div>
                    </CollapsibleContent>
                </Collapsible>
            ) : null}
        </div>
    )
}
