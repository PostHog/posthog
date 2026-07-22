import { useActions, useValues } from 'kea'

import { IconCollapse, IconExpand, IconExternal, IconWarning } from '@posthog/icons'

import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { colonDelimitedDuration } from 'lib/utils/durations'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import type {
    ExperimentSessionContextItemApi,
    ExperimentSessionMetricHitApi,
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

// Above this many in-bounds occurrences the per-event seek chips collapse behind a toggle so a
// busy metric doesn't flood the sidebar.
const INLINE_METRIC_EVENT_LIMIT = 6

function MetricEventChips({
    seekPoints,
    onSeek,
}: {
    seekPoints: { ms: number; offsetSeconds: number }[]
    onSeek: (timestampMs: number) => void
}): JSX.Element {
    return (
        <div className="flex flex-row flex-wrap gap-1 pl-3">
            {seekPoints.map(({ ms, offsetSeconds }) => (
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
    // Only in-bounds occurrences are seekable — the backend's ±1h slack can place some outside the
    // playable recording. Each becomes a chip labelled with its offset from the recording start.
    const seekPoints = hit.timestamps
        .map((timestamp) => dayjs(timestamp).valueOf())
        .filter((ms): ms is number => isWithinRecording(ms))
        .map((ms) => ({ ms, offsetSeconds: recordingStartMs != null ? Math.floor((ms - recordingStartMs) / 1000) : 0 }))

    return (
        <div className="flex flex-col gap-y-0.5 min-w-0 pl-3 text-xs">
            <span className="truncate">{hit.metric_name}</span>
            {seekPoints.length === 0 ? (
                <span className="pl-3 text-muted">Fired outside the recording</span>
            ) : seekPoints.length > INLINE_METRIC_EVENT_LIMIT ? (
                <LemonCollapse
                    embedded
                    size="small"
                    panels={[
                        {
                            key: 'events',
                            header: `${seekPoints.length} events`,
                            content: <MetricEventChips seekPoints={seekPoints} onSeek={onSeek} />,
                        },
                    ]}
                />
            ) : (
                <MetricEventChips seekPoints={seekPoints} onSeek={onSeek} />
            )}
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

// Position of the exposure within the recording, so the list's chronological order is legible rather than
// implied. Deliberately always relative (not the player's Relative/UTC/device setting like the inspector's
// ItemTimeDisplay): "where in this recording" is the whole point here, and an absolute date would not fit
// the sidebar's width. An exposure captured before the recording starts clamps to zero — the row's tooltip
// is what explains that it landed outside the playable range.
function ExposureTime({ timeInRecording }: { timeInRecording: number }): JSX.Element {
    return (
        <span className="text-secondary text-xs tabular-nums shrink-0 min-w-10 text-right">
            {colonDelimitedDuration(Math.max(0, timeInRecording) / 1000, null)}
        </span>
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
    // Leading slot rendered before the timestamp — the metric-events expand toggle, or an empty
    // spacer of the same width so the timestamp and name columns line up across rows.
    leading?: JSX.Element | null
}): JSX.Element {
    let name: JSX.Element
    if (onSeek) {
        name = (
            <Link
                title="Jump to when this session matched the experiment's exposure criteria"
                onClick={onSeek}
                data-attr="replay-experiment-context-jump-to-first-exposure"
            >
                {item.experiment_name}
            </Link>
        )
    } else if (outOfWindow) {
        name = (
            <Tooltip title={OUT_OF_WINDOW_TOOLTIP}>
                <span>{item.experiment_name}</span>
            </Tooltip>
        )
    } else {
        name = <span>{item.experiment_name}</span>
    }

    // The name lives in its own flex-1 truncate box so the variant tag and open-experiment icon
    // stay right-aligned whether the name is a plain span or a Link (a Link with no `to` renders a
    // button wrapped in a non-flex span, which would otherwise let its tag hug the text).
    return (
        <div className="flex flex-row items-center gap-x-2 min-w-0">
            {leading}
            {timeInRecording != null ? <ExposureTime timeInRecording={timeInRecording} /> : null}
            <div className="flex-1 min-w-0 truncate">{name}</div>
            <VariantTag item={item} />
            <OpenExperimentButton item={item} />
        </div>
    )
}

export function PlayerSidebarExperimentsSection(): JSX.Element | null {
    const { logicProps, sessionPlayerData } = useValues(sessionRecordingPlayerLogic)
    const { seekToTimestamp } = useActions(sessionRecordingPlayerLogic)
    const experimentContextLogic = sessionRecordingExperimentContextLogic({
        sessionRecordingId: logicProps.sessionRecordingId,
    })
    const { seenItems, enrolledItems, hasExperimentContext, expandedExperimentIds } = useValues(experimentContextLogic)
    const { setExperimentExpanded } = useActions(experimentContextLogic)

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

    return (
        <div
            className="rounded border bg-surface-primary px-2 py-1 flex flex-col gap-y-1"
            data-attr="replay-experiment-context-overview"
        >
            <h4 className="font-semibold text-xs mb-0">Experiments</h4>

            {seenItems.map((item) => {
                const exposedAtMs = item.first_exposure_timestamp
                    ? dayjs(item.first_exposure_timestamp).valueOf()
                    : null
                const canSeek = isWithinRecording(exposedAtMs)
                // Distinguish "seen but outside the window" (worth a tooltip) from "bounds not known
                // yet" (transient, no tooltip) so we never explain a non-jump we can't actually vouch for.
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
                                anySeenExpandable ? (
                                    <div className="shrink-0 flex w-[1.625rem] justify-center">
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
                                        ) : null}
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
            })}

            {enrolledItems.length > 0 ? (
                <LemonCollapse
                    embedded
                    size="small"
                    panels={[
                        {
                            key: 'enrolled',
                            header: `Also enrolled, not exposed in this session (${enrolledItems.length})`,
                            content: (
                                <div className="flex flex-col gap-y-1">
                                    {enrolledItems.map((item) => (
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
