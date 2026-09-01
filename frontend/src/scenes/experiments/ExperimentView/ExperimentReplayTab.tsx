import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'
import { Fragment } from 'react'

import { IconChevronDown, IconInfo } from '@posthog/icons'
import { LemonBanner, LemonCard, LemonSegmentedButton, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { pluralize } from 'lib/utils/strings'
import { SessionRecordingsPlaylist } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import { sessionRecordingsPlaylistLogic } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { urls } from 'scenes/urls'

import { Experiment } from '~/types'

import { isLaunched } from 'products/experiments/frontend/experimentStatus'
import { experimentScannerParams } from 'products/replay_vision/frontend/replay_scanners/experimentTargeting'
import { scannerTypeLabel } from 'products/replay_vision/frontend/replay_scanners/types'

import { NOT_A_FUNNEL_REASON } from '../utils'
import { ExperimentBehaviorComparison, ExperimentBehaviorComparisonToggle } from './ExperimentBehaviorComparison'
import {
    ExperimentReplayMetricFilterMode,
    ExperimentReplayMetricOption,
    ExperimentSessionBucket,
    LinkedScanner,
    experimentReplayTabLogic,
} from './experimentReplayTabLogic'
import { VariantTag } from './VariantTag'

// LemonSegmentedButton values must be strings; the logic stores null for "All". '$' is not an
// allowed character in variant keys, so the '$' prefix guarantees no collision with a real
// variant — a variant literally named "all" just renders as its own option after the built-in "All".
const ALL_VARIANTS = '$all'

// Unchanged from the earlier cross-sell wording, so a dismissal there still holds. Someone who
// turned down scanners for this experiment did not ask to be told again in purple.
const SCANNER_CROSS_SELL_DISMISS_KEY = 'experiment-replay-vision-scanner-cross-sell'

// What the unfiltered list is, said once above it. The second sentence carries the part that
// isn't guessable: exposure is resolved per person, matching who the analysis counts, so
// sessions appear even when the exposure event fired server-side or in an earlier session.
const POPULATION_CAPTION =
    "Showing sessions of exposed participants from their first exposure onward. The exposure event itself doesn't have to be in the session."

// A session fires a metric's events, never the metric — the caption spells that out where it
// has the room the trigger doesn't.
const MODE_SUMMARIES: Record<ExperimentReplayMetricFilterMode, string> = {
    fired_all: 'fired events from every selected metric',
    fired_any: 'fired events from at least one selected metric',
    no_metric_activity: 'fired no events from the selected metrics',
    funnel_dropoff: "were exposed but didn't finish the funnel",
}

/**
 * What the trigger says, so the current mode is readable without opening the menu.
 *
 * The count is always of *metrics* — that's what the checkboxes select. A metric can count
 * several events (a ratio counts two, a funnel one per step), so counting events here would
 * disagree with the number of boxes ticked. The mode verb carries the events half: what a
 * session fires is a metric's events, never the metric itself.
 */
function metricFilterTriggerLabel(
    mode: ExperimentReplayMetricFilterMode,
    selectedUuids: string[],
    options: ExperimentReplayMetricOption[]
): string {
    if (mode === 'funnel_dropoff') {
        const selected = options.find((option) => option.uuid === selectedUuids[0])
        return selected ? `Didn't finish funnel: ${selected.name}` : "Didn't finish funnel"
    }
    if (selectedUuids.length === 0) {
        // Never fall back to the neutral label for a non-default mode: the mode is on, and the
        // caption below is what explains why it isn't narrowing anything yet.
        return mode === 'fired_all' ? 'Metric events' : mode === 'fired_any' ? 'Fired any' : 'No metric events'
    }
    const metrics = pluralize(selectedUuids.length, 'metric')
    if (selectedUuids.length === 1) {
        // "all of" and "any of" one metric are the same question, and both quantifiers read as
        // noise next to a count of one.
        return mode === 'no_metric_activity' ? `Didn't fire ${metrics}` : `Fired ${metrics}`
    }
    if (mode === 'fired_any') {
        return `Fired any of ${metrics}`
    }
    if (mode === 'no_metric_activity') {
        return `Fired none of ${metrics}`
    }
    return `Fired all ${metrics}`
}

/** Why a picked mode isn't narrowing the list — it needs a selection it doesn't have yet. */
function unappliedModeReason(mode: ExperimentReplayMetricFilterMode): string {
    return mode === 'funnel_dropoff'
        ? 'Pick a funnel metric whose last step can be matched to recordings. Showing every exposed recording until then.'
        : 'Pick at least one metric. Showing every exposed recording until then.'
}

/**
 * States what the server-computed set does and doesn't cover. Every clause is load-bearing: the
 * list is capped, the scan window is clamped, and "in this session" is the honest unit — the
 * experiment analysis counts per person over the whole run window.
 */
function bucketCaption(bucket: ExperimentSessionBucket): string {
    const { session_ids, truncated, considered_metrics, excluded_metrics, filter_test_accounts } = bucket.response
    if (session_ids.length === 0) {
        return 'No recordings matched this filter.'
    }
    const sessions = truncated
        ? `Showing the ${session_ids.length} most recent recordings that`
        : `Showing ${pluralize(session_ids.length, 'recording')} that`
    const what =
        bucket.request.bucket === 'no_metric_activity'
            ? `fired no events from ${pluralize(considered_metrics.length, 'metric')} in this session`
            : bucket.request.bucket === 'fired_any' && considered_metrics.length === 1
              ? // One metric needs no quantifier, and naming it beats "at least one selected metric".
                `fired events from ${considered_metrics[0].metric_name} in this session`
              : `${MODE_SUMMARIES[bucket.request.bucket as ExperimentReplayMetricFilterMode]}, in this session`
    const caveats = [
        filter_test_accounts ? 'test accounts excluded' : null,
        excluded_metrics.length > 0
            ? `${pluralize(excluded_metrics.length, 'metric')} left out: ${excluded_metrics
                  .map((metric) => metric.metric_name)
                  .join(', ')}`
            : null,
    ].filter(Boolean)
    return `${sessions} ${what}.${caveats.length > 0 ? ` ${caveats.join('. ')}.` : ''}`
}

/** A metric row: its name, plus the events a session actually has to have fired to match it. */
function MetricOptionLabel({ option }: { option: ExperimentReplayMetricOption }): JSX.Element {
    return (
        <span className="flex min-w-0 items-baseline gap-2">
            <span className="truncate">{option.name}</span>
            {option.eventNames.length > 0 && (
                <span className="shrink-0 text-xs text-muted">{option.eventNames.join(', ')}</span>
            )}
        </span>
    )
}

const METRIC_FILTER_MODE_OPTIONS: { value: ExperimentReplayMetricFilterMode; label: string; tooltip: string }[] = [
    {
        value: 'fired_all',
        label: 'Fired all',
        tooltip: 'Sessions that fired events for every selected metric.',
    },
    {
        value: 'fired_any',
        label: 'Fired any',
        tooltip: 'Sessions that fired events for at least one of the selected metrics.',
    },
    {
        value: 'no_metric_activity',
        label: 'Fired none',
        tooltip:
            'Sessions that fired no events for any of the selected metrics. Select nothing to use every metric that can be matched.',
    },
    {
        value: 'funnel_dropoff',
        label: "Didn't finish funnel",
        tooltip:
            "Sessions that saw the experiment but didn't fire a funnel metric's last step during the recording. The exposure counts as the funnel's first step. The same person may have finished it in a later session.",
    },
]

/** Placeholder for the watching-scanners card while the lookup is in flight, so the tab doesn't
 * flash the cross-sell banner before the card resolves. */
function LinkedScannersSkeletonCard(): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="mb-2 p-3" data-attr="experiment-recordings-linked-scanners-loading">
            <LemonSkeleton className="h-5 w-64 mb-2" />
            <LemonSkeleton className="h-4 w-full" repeat={2} />
        </LemonCard>
    )
}

/** The scanners already watching this experiment, one row each, with a link and a monthly count. */
function LinkedScannersCard({
    scanners,
    addAnotherUrl,
    onAddAnother,
}: {
    scanners: LinkedScanner[]
    addAnotherUrl: string
    onAddAnother: () => void
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="mb-2 p-3" data-attr="experiment-recordings-linked-scanners">
            <div className="flex items-center justify-between gap-2 mb-2">
                <span className="font-semibold">Scanners watching this experiment</span>
                <LemonButton
                    type="secondary"
                    size="small"
                    to={addAnotherUrl}
                    onClick={() => onAddAnother()}
                    data-attr="experiment-recordings-scanner-add-another"
                >
                    Add another
                </LemonButton>
            </div>
            <div className="flex flex-col gap-1">
                {scanners.map((scanner) => (
                    <div key={scanner.id} className="flex items-center justify-between gap-2">
                        <span className="flex items-center gap-2 min-w-0">
                            <Link to={urls.replayVision(scanner.id)} className="truncate">
                                {scanner.name}
                            </Link>
                            <LemonTag type="muted">{scannerTypeLabel(scanner.scannerType)}</LemonTag>
                        </span>
                        <span className="text-muted shrink-0">
                            {pluralize(scanner.observationsThisMonth, 'observation')} this month
                        </span>
                    </div>
                ))}
            </div>
        </LemonCard>
    )
}

export function ExperimentReplayTab({ experiment }: { experiment: Experiment }): JSX.Element {
    const logic = experimentReplayTabLogic({ experiment })
    const {
        effectiveVariantKey,
        variantKeys,
        recordingsFilters,
        effectiveMetricUuids,
        metricOptions,
        metricFilterMode,
        sessionBucket,
        sessionBucketLoading,
        sessionBucketError,
        sessionBucketRequest,
        linkedScanners,
        linkedScannersLoading,
    } = useValues(logic)
    const {
        setSelectedVariantKey,
        setMetricSelected,
        setMetricFilterMode,
        loadSessionBucket,
        playlistFiltersChanged,
        recordingsLoaded,
        recordingOpened,
        scannerCrossSellClicked,
    } = useActions(logic)
    const scannerCrossSellEnabled = useFeatureFlag('VISION_ENTRYPOINT_EXPERIMENTS')

    // One object feeds both the playlist below and the findMounted lookup, because the logic's
    // kea key is derived from these props: hand-duplicating them at the two sites would let the
    // keys drift apart, and a drifted key turns every highlight click into a silent no-op.
    const playlistLogicProps = { logicKey: `experiment-${experiment.id}`, updateSearchParams: false }
    // `findMounted` rather than building the logic: the playlist below owns it and passes props
    // this call doesn't have, so building it from here first would leave it mounted with a
    // half-built set of them. Before the playlist has rendered there is nothing to select anyway.
    const watchRecording = (sessionId: string): boolean => {
        const playlist = sessionRecordingsPlaylistLogic.findMounted(playlistLogicProps)
        if (!playlist) {
            return false
        }
        playlist.actions.setSelectedRecordingId(sessionId)
        return true
    }

    if (!isLaunched(experiment)) {
        return <LemonBanner type="info">Launch the experiment to see recordings of participants.</LemonBanner>
    }

    // Selectable metrics render as checkboxes. The rest move to labelled sections that explain
    // once, via a section tooltip, why they can't be matched — instead of repeating the same
    // reason on every row. One section per distinct reason, since metrics can be unmatchable for
    // different reasons (server-side events, a retention window, data-warehouse-only sources, or
    // simply not being a funnel while the drop-off mode is on).
    const linkableMetricOptions = metricOptions.filter(
        (option) => !option.unlinkable && (metricFilterMode !== 'funnel_dropoff' || option.dropoffReason === null)
    )
    const unselectableOptionsByReason = new Map<string, ExperimentReplayMetricOption[]>()
    for (const option of metricOptions) {
        const reason = option.unlinkable
            ? option.unlinkableReason
            : metricFilterMode === 'funnel_dropoff'
              ? option.dropoffReason
              : null
        if (reason) {
            unselectableOptionsByReason.set(reason, [...(unselectableOptionsByReason.get(reason) ?? []), option])
        }
    }

    const scannerSetupUrl = combineUrl(
        urls.replayVisionScannerTemplate('new'),
        experimentScannerParams({
            experimentId: experiment.id as number,
            variantKey: effectiveVariantKey,
        })
    ).url

    return (
        <div data-attr="experiment-recordings-tab">
            {scannerCrossSellEnabled &&
                (linkedScannersLoading ? (
                    <LinkedScannersSkeletonCard />
                ) : linkedScanners.length > 0 ? (
                    <LinkedScannersCard
                        scanners={linkedScanners}
                        addAnotherUrl={scannerSetupUrl}
                        onAddAnother={scannerCrossSellClicked}
                    />
                ) : (
                    <LemonBanner
                        type="ai"
                        className="mb-2"
                        dismissKey={SCANNER_CROSS_SELL_DISMISS_KEY}
                        action={{
                            children: 'Set up scanner for this experiment',
                            to: scannerSetupUrl,
                            onClick: () => scannerCrossSellClicked(),
                            'data-attr': 'experiment-recordings-scanner-cross-sell',
                        }}
                    >
                        Replay vision is here. Scanners watch your recordings for you and surface what matters.
                    </LemonBanner>
                ))}
            <div className="mb-2 flex flex-wrap gap-2">
                <LemonSegmentedButton
                    size="small"
                    value={effectiveVariantKey ?? ALL_VARIANTS}
                    onChange={(value) => setSelectedVariantKey(value === ALL_VARIANTS ? null : value)}
                    options={[
                        { value: ALL_VARIANTS, label: 'All' },
                        ...variantKeys.map((key) => ({ value: key, label: <VariantTag variantKey={key} /> })),
                    ]}
                />
                {metricOptions.length > 0 && (
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={
                                <LemonButton
                                    size="small"
                                    type="secondary"
                                    sideIcon={<IconChevronDown />}
                                    tooltip="Narrow the list by what fired in each session. Whether a session fired a metric's events can differ from what the experiment analysis counts."
                                    data-attr="experiment-recordings-metric-filter"
                                />
                            }
                        >
                            {metricFilterTriggerLabel(metricFilterMode, effectiveMetricUuids, metricOptions)}
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start" className="min-w-fit max-w-100">
                            <div className="p-1">
                                <LemonSegmentedButton
                                    size="xsmall"
                                    fullWidth
                                    value={metricFilterMode}
                                    onChange={(value) => setMetricFilterMode(value)}
                                    options={METRIC_FILTER_MODE_OPTIONS}
                                />
                            </div>
                            <DropdownMenuSeparator />
                            {linkableMetricOptions.map((option) => (
                                <DropdownMenuCheckboxItem
                                    key={option.uuid}
                                    checked={effectiveMetricUuids.includes(option.uuid)}
                                    onCheckedChange={(checked: boolean) => setMetricSelected(option.uuid, checked)}
                                    closeOnClick={false}
                                    data-attr="experiment-recordings-metric-option"
                                >
                                    <MetricOptionLabel option={option} />
                                </DropdownMenuCheckboxItem>
                            ))}
                            {[...unselectableOptionsByReason.entries()].map(([reason, options], index) => (
                                // Fragment, not a wrapper element: the separator, label, and items
                                // must stay direct children of the menu for keyboard nav and ARIA.
                                <Fragment key={reason}>
                                    {(linkableMetricOptions.length > 0 || index > 0) && <DropdownMenuSeparator />}
                                    {/* Quill's DropdownMenuLabel renders a Base UI GroupLabel, which must
                                        live inside a DropdownMenuGroup or it throws at render. */}
                                    <DropdownMenuGroup>
                                        <DropdownMenuLabel inset className="flex items-center gap-1">
                                            {reason === NOT_A_FUNNEL_REASON
                                                ? 'Needs a funnel metric'
                                                : "Can't match to recordings"}
                                            <Tooltip title={reason}>
                                                <IconInfo className="size-3 shrink-0" />
                                            </Tooltip>
                                        </DropdownMenuLabel>
                                        {options.map((option) => (
                                            // Informational only — not selectable. The section label above
                                            // carries the explanation shared by this section's metrics.
                                            <DropdownMenuItem
                                                key={option.uuid}
                                                inset
                                                disabled
                                                data-attr="experiment-recordings-metric-option"
                                            >
                                                <MetricOptionLabel option={option} />
                                            </DropdownMenuItem>
                                        ))}
                                    </DropdownMenuGroup>
                                </Fragment>
                            ))}
                        </DropdownMenuContent>
                    </DropdownMenu>
                )}
                <ExperimentBehaviorComparisonToggle experiment={experiment} />
            </div>
            {/* The default mode also uses the endpoint for a single multi-source metric, so the
                caption follows the request, not the mode. */}
            <div className="mb-2 flex items-center gap-2 text-xs text-secondary">
                {!sessionBucketRequest && metricFilterMode === 'fired_all' ? (
                    effectiveMetricUuids.length === 0 ? (
                        <span data-attr="experiment-recordings-population-caption">{POPULATION_CAPTION}</span>
                    ) : null
                ) : !sessionBucketRequest ? (
                    <span>{unappliedModeReason(metricFilterMode)}</span>
                ) : sessionBucketError !== null ? (
                    <>
                        <span>Couldn't work out which sessions match this filter: {sessionBucketError}</span>
                        <LemonButton size="xsmall" type="secondary" onClick={() => loadSessionBucket()}>
                            Try again
                        </LemonButton>
                    </>
                ) : sessionBucketLoading || !sessionBucket ? (
                    <span>Finding matching sessions…</span>
                ) : (
                    <span data-attr="experiment-recordings-bucket-caption">{bucketCaption(sessionBucket)}</span>
                )}
            </div>
            <ExperimentBehaviorComparison experiment={experiment} onWatchRecording={watchRecording} />
            <div className="SessionRecordingPlaylistHeightWrapper">
                <SessionRecordingsPlaylist
                    {...playlistLogicProps}
                    analyticsSource="experiment-recordings-tab"
                    filters={recordingsFilters}
                    onFiltersChange={(filters) => playlistFiltersChanged(filters)}
                    onRecordingsLoaded={(recordings) => recordingsLoaded(recordings)}
                    onRecordingSelected={(recordingId) => recordingOpened(recordingId)}
                />
            </div>
        </div>
    )
}
