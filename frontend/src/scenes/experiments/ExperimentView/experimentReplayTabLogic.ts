import {
    MakeLogicType,
    actions,
    afterMount,
    beforeUnmount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'

import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { groupBy } from 'lib/utils/arrays'
import {
    ExperimentRecordingsBucketFailedContext,
    ExperimentRecordingsBucketLoadedContext,
    ExperimentRecordingsFilterContext,
    ExperimentRecordingsTabContext,
    ExperimentWatchCardContext,
    ExperimentWatchHighlightContext,
    ExperimentWatchShelfContext,
    eventUsageLogic,
} from 'lib/utils/eventUsageLogic'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { playerSidebarLogic } from 'scenes/session-recordings/player/sidebar/playerSidebarLogic'
import { DEFAULT_RECORDING_FILTERS } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'
import { teamLogic } from 'scenes/teamLogic'

import {
    ExperimentMetric,
    NodeKind,
    ProductIntentContext,
    ProductKey,
    isExperimentRetentionMetric,
} from '~/queries/schema/schema-general'
import {
    Experiment,
    FilterLogicalOperator,
    RecordingUniversalFilters,
    SessionRecordingSidebarTab,
    SessionRecordingType,
    UniversalFiltersGroupValue,
} from '~/types'

import {
    experimentsSessionBucketsCreate,
    experimentsSessionContextsCreate,
    experimentsSessionEventDeltasCreate,
} from 'products/experiments/frontend/generated/api'
import { ExperimentWatchCardKindEnumApi } from 'products/experiments/frontend/generated/api.schemas'
import type {
    ExperimentSessionBucketResponseApi,
    ExperimentSessionBucketEnumApi,
    ExperimentSessionEventDeltaResponseApi,
    ExperimentWatchCardApi,
} from 'products/experiments/frontend/generated/api.schemas'
import { visionScannersList } from 'products/replay_vision/frontend/generated/api'
import type { ScannerTypeEnumApi } from 'products/replay_vision/frontend/generated/api.schemas'

import type { ExperimentIdType } from '../../../types'
import type { ExperimentSavedMetric } from '../experimentLogic'
import { getDefaultMetricTitle } from '../MetricsView/shared/utils'
import {
    getExperimentVariants,
    getFunnelDropoffReason,
    getMetricSessionFilters,
    isUnlinkableEventFilter,
} from '../utils'
import {
    DATA_WAREHOUSE_UNLINKABLE_REASON,
    METRIC_UNLINKABLE_REASON,
    RETENTION_UNLINKABLE_REASON,
    viewRecordingsLinkabilityLogic,
} from '../viewRecordingsLinkabilityLogic'

export interface ExperimentReplayTabLogicProps {
    experiment: Experiment
}

/** A scanner already watching this experiment, for the back-link on the Recordings tab. */
export interface LinkedScanner {
    id: string
    name: string
    scannerType: ScannerTypeEnumApi
    observationsThisMonth: number
}

/** One experiment metric offered in the recordings tab's "Metric events" dropdown. */
export interface ExperimentReplayMetricOption {
    uuid: string
    name: string
    filters: UniversalFiltersGroupValue[]
    unlinkable: boolean
    /** Why the metric can't narrow the playlist, shown alongside it. Null when it can. */
    unlinkableReason: string | null
    /** Why drop-off can't be asked of this metric, shown alongside it. Null when it can. */
    dropoffReason: string | null
    /** The events the metric counts, deduped — a metric's name rarely says which they are. */
    eventNames: string[]
}

/**
 * How the selected metrics narrow the list.
 *
 * `fired_all` composes event filters client-side and is uncapped. The other three are server
 * computed: the recordings query carries one operator for its whole filter tree, so an OR, an
 * absence, and a drop-off can only come back as an explicit session-id list — which the endpoint
 * bounds, so those modes show a capped, most-recent-first slice.
 */
export type ExperimentReplayMetricFilterMode = 'fired_all' | 'fired_any' | 'no_metric_activity' | 'funnel_dropoff'

/** What the tab asks the bucket endpoint for, and the spec a loaded response belongs to. */
export interface ExperimentSessionBucketRequest {
    bucket: ExperimentSessionBucketEnumApi
    metric_uuids: string[]
    variant: string | null
}

export interface ExperimentSessionBucket {
    request: ExperimentSessionBucketRequest
    response: ExperimentSessionBucketResponseApi
}

/**
 * What a watch card needs to describe a recording it names, taken from the page the playlist has
 * already loaded rather than fetched again: the card's session ids are exactly what the list is
 * filtered to, so the list is holding this by the time a card can be selected.
 */
export type ExperimentReplayRecording = Pick<SessionRecordingType, 'id' | 'recording_duration' | 'person'>

// Mirrors the backend's MAX_SESSION_CONTEXT_BATCH — ids beyond it would 400 the whole batch.
const SESSION_CONTEXT_PREFETCH_LIMIT = 20

/**
 * Sort metrics the way the experiment's metrics page lists them. The ordering arrays are that
 * page's display order, and every metric uuid is meant to be in one of them — but only sorting
 * on them, never filtering, so a metric missing from the arrays still shows up (last) rather
 * than vanishing from the filter with no trace.
 */
function metricDisplayOrder(experiment: Experiment): (a: { uuid: string }, b: { uuid: string }) => number {
    const order = [
        ...(experiment.primary_metrics_ordered_uuids || []),
        ...(experiment.secondary_metrics_ordered_uuids || []),
    ]
    const rank = (uuid: string): number => {
        const index = order.indexOf(uuid)
        // Not MAX_SAFE_INTEGER arithmetic on both sides — equal ranks must subtract to 0 so the
        // sort stays stable and unlisted metrics keep their existing relative order.
        return index === -1 ? order.length : index
    }
    return (a, b) => rank(a.uuid) - rank(b.uuid)
}

/**
 * The distinct events a metric counts. A metric's name is free text ("Rageclicks per user"), so
 * on its own it doesn't say what a session has to have fired to match.
 */
function metricSourceEventNames(metric: ExperimentMetric): string[] {
    const names = getMetricSessionFilters(metric)
        // Only entity filters name an event; a nested filter group (which the type allows) doesn't.
        .flatMap((filter) => ('id' in filter ? [String(filter.name ?? filter.id ?? '')] : []))
        .filter(Boolean)
    return [...new Set(names)]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface experimentReplayTabLogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    currentProjectId: number | string // teamLogic
    linkabilityLoaded: boolean // viewRecordingsLinkabilityLogic
    seenTogetherMapLoading: boolean // viewRecordingsLinkabilityLogic
    unlinkableEventNames: Set<string> // viewRecordingsLinkabilityLogic
    behaviorComparisonAvailable: boolean
    behaviorComparisonOpen: boolean
    bucketSessionIds: string[] | undefined
    effectiveMetricUuids: string[]
    effectiveVariantKey: string | null
    linkedScanners: LinkedScanner[]
    linkedScannersLoading: boolean
    loadedRecordings: ExperimentReplayRecording[]
    loadedRecordingsById: Map<string, ExperimentReplayRecording>
    metricFilterMode: ExperimentReplayMetricFilterMode
    metricOptions: ExperimentReplayMetricOption[]
    recordingsFilters: RecordingUniversalFilters
    selectedMetricUuids: string[]
    selectedVariantKey: string | null
    selectedWatchCard: ExperimentWatchCardApi | null
    sessionBucket: ExperimentSessionBucket | null
    sessionBucketError: string | null
    sessionBucketLoading: boolean
    sessionBucketRequest: ExperimentSessionBucketRequest | null
    sessionEventDeltas: ExperimentSessionEventDeltaResponseApi | null
    sessionEventDeltasError: string | null
    sessionEventDeltasLoading: boolean
    variantKeys: string[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface experimentReplayTabLogicActions {
    reportExperimentBehaviorComparisonLoaded: (
        experimentId: ExperimentIdType,
        context: ExperimentWatchShelfContext
    ) => {
        context: ExperimentWatchShelfContext
        experimentId: ExperimentIdType
    } // eventUsageLogic
    reportExperimentBehaviorComparisonToggled: (
        experimentId: ExperimentIdType,
        opened: boolean
    ) => {
        experimentId: ExperimentIdType
        opened: boolean
    } // eventUsageLogic
    reportExperimentRecordingOpened: (
        experimentId: ExperimentIdType,
        context: ExperimentRecordingsFilterContext
    ) => {
        context: ExperimentRecordingsFilterContext
        experimentId: ExperimentIdType
    } // eventUsageLogic
    reportExperimentRecordingsBucketFailed: (
        experimentId: ExperimentIdType,
        context: ExperimentRecordingsBucketFailedContext
    ) => {
        context: ExperimentRecordingsBucketFailedContext
        experimentId: ExperimentIdType
    } // eventUsageLogic
    reportExperimentRecordingsBucketLoaded: (
        experimentId: ExperimentIdType,
        context: ExperimentRecordingsBucketLoadedContext
    ) => {
        context: ExperimentRecordingsBucketLoadedContext
        experimentId: ExperimentIdType
    } // eventUsageLogic
    reportExperimentRecordingsTabViewed: (
        experimentId: ExperimentIdType,
        context: ExperimentRecordingsTabContext
    ) => {
        context: ExperimentRecordingsTabContext
        experimentId: ExperimentIdType
    } // eventUsageLogic
    reportExperimentWatchCardSelected: (
        experimentId: ExperimentIdType,
        context: ExperimentWatchCardContext
    ) => {
        context: ExperimentWatchCardContext
        experimentId: ExperimentIdType
    } // eventUsageLogic
    reportExperimentWatchHighlightOpened: (
        experimentId: ExperimentIdType,
        context: ExperimentWatchHighlightContext
    ) => {
        context: ExperimentWatchHighlightContext
        experimentId: ExperimentIdType
    } // eventUsageLogic
    setDefaultTab: (tab: SessionRecordingSidebarTab) => {
        tab: SessionRecordingSidebarTab
    } // playerSidebarLogic
    loadSeenTogetherFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    } // viewRecordingsLinkabilityLogic
    loadSeenTogetherSuccess: (
        seenTogetherMap: Record<string, boolean>,
        payload?: any
    ) => {
        payload?: any
        seenTogetherMap: Record<string, boolean>
    } // viewRecordingsLinkabilityLogic
    loadLinkedScanners: (_?: unknown) => unknown
    loadLinkedScannersFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadLinkedScannersSuccess: (
        linkedScanners: {
            id: string
            name: string
            observationsThisMonth: number
            scannerType: ScannerTypeEnumApi
        }[],
        payload?: unknown
    ) => {
        linkedScanners: {
            id: string
            name: string
            observationsThisMonth: number
            scannerType: ScannerTypeEnumApi
        }[]
        payload?: unknown
    }
    loadSessionBucket: (_?: unknown) => unknown
    loadSessionBucketFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSessionBucketSuccess: (
        sessionBucket: {
            request: ExperimentSessionBucketRequest
            response: ExperimentSessionBucketResponseApi
        } | null,
        payload?: unknown
    ) => {
        sessionBucket: {
            request: ExperimentSessionBucketRequest
            response: ExperimentSessionBucketResponseApi
        } | null
        payload?: unknown
    }
    loadSessionEventDeltas: (_?: unknown) => unknown
    loadSessionEventDeltasFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSessionEventDeltasSuccess: (
        sessionEventDeltas: ExperimentSessionEventDeltaResponseApi,
        payload?: unknown
    ) => {
        sessionEventDeltas: ExperimentSessionEventDeltaResponseApi
        payload?: unknown
    }
    playlistFiltersChanged: (filters: RecordingUniversalFilters) => {
        filters: RecordingUniversalFilters
    }
    prefetchSessionContexts: (sessionIds: string[]) => {
        sessionIds: string[]
    }
    recordingOpened: (sessionId: string) => {
        sessionId: string
    }
    recordingsLoaded: (recordings: ExperimentReplayRecording[]) => {
        recordings: ExperimentReplayRecording[]
    }
    reportTabViewed: () => {
        value: true
    }
    scannerCrossSellClicked: () => {
        value: true
    }
    selectWatchCard: (card: ExperimentWatchCardApi | null) => {
        card: ExperimentWatchCardApi | null
    }
    setMetricFilterMode: (mode: ExperimentReplayMetricFilterMode) => {
        mode: ExperimentReplayMetricFilterMode
    }
    setMetricSelected: (
        metricUuid: string,
        selected: boolean
    ) => {
        metricUuid: string
        selected: boolean
    }
    setSelectedVariantKey: (variantKey: string | null) => {
        variantKey: string | null
    }
    toggleBehaviorComparison: () => {
        value: true
    }
    watchHighlightOpened: (
        card: ExperimentWatchCardApi,
        position: number
    ) => {
        card: ExperimentWatchCardApi
        position: number
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface experimentReplayTabLogicMeta {
    key: ExperimentIdType
    __keaTypeGenInternalSelectorTypes: {
        loadedRecordingsById: (loadedRecordings: ExperimentReplayRecording[]) => Map<string, ExperimentReplayRecording>
        variantKeys: (arg: any) => string[]
        behaviorComparisonAvailable: (featureFlags: FeatureFlagsSet) => boolean
        effectiveVariantKey: (selectedVariantKey: string | null, variantKeys: string[]) => string | null
        metricOptions: (
            linkabilityLoaded: boolean,
            unlinkableEventNames: Set<string>,
            arg: any
        ) => ExperimentReplayMetricOption[]
        effectiveMetricUuids: (
            selectedMetricUuids: string[],
            metricOptions: ExperimentReplayMetricOption[],
            metricFilterMode: ExperimentReplayMetricFilterMode
        ) => string[]
        sessionBucketRequest: (
            metricFilterMode: ExperimentReplayMetricFilterMode,
            effectiveMetricUuids: string[],
            effectiveVariantKey: string | null,
            metricOptions: ExperimentReplayMetricOption[]
        ) => ExperimentSessionBucketRequest | null
        bucketSessionIds: (
            sessionBucketRequest: ExperimentSessionBucketRequest | null,
            sessionBucket: ExperimentSessionBucket | null,
            sessionBucketError: string | null
        ) => string[] | undefined
        recordingsFilters: (
            effectiveVariantKey: string | null,
            effectiveMetricUuids: string[],
            metricOptions: ExperimentReplayMetricOption[],
            unlinkableEventNames: Set<string>,
            seenTogetherMapLoading: boolean,
            bucketSessionIds: string[] | undefined,
            selectedWatchCard: ExperimentWatchCardApi | null,
            arg: any
        ) => RecordingUniversalFilters
    }
}

export type experimentReplayTabLogicType = MakeLogicType<
    experimentReplayTabLogicValues,
    experimentReplayTabLogicActions,
    ExperimentReplayTabLogicProps,
    experimentReplayTabLogicMeta
>

/**
 * Backs the experiment "Recordings" tab: sessions exposed to the experiment over its run window,
 * narrowed by the variant facet and the metric facet ("replays that reached this metric").
 */
export const experimentReplayTabLogic = kea<experimentReplayTabLogicType>([
    props({} as ExperimentReplayTabLogicProps),
    key((props) => props.experiment.id ?? 'new'),
    path((key) => ['scenes', 'experiments', 'ExperimentView', 'experimentReplayTabLogic', String(key)]),
    connect((props: ExperimentReplayTabLogicProps) => ({
        // Same key as the metric buttons' lookup, so the two surfaces share one `seen_together` request.
        values: [
            viewRecordingsLinkabilityLogic({ experiment: props.experiment }),
            ['unlinkableEventNames', 'linkabilityLoaded', 'seenTogetherMapLoading'],
            featureFlagLogic,
            ['featureFlags'],
            teamLogic,
            ['currentProjectId'],
        ],
        // Mounts the sidebar singleton for this tab's lifetime, so the default below outlives the
        // player remounting as the viewer moves between recordings in the playlist.
        actions: [
            playerSidebarLogic,
            ['setDefaultTab'],
            // The health of a tab view is only known once the linkability check resolves, so the
            // view is reported off these rather than from `afterMount`.
            viewRecordingsLinkabilityLogic({ experiment: props.experiment }),
            ['loadSeenTogetherSuccess', 'loadSeenTogetherFailure'],
            eventUsageLogic,
            [
                'reportExperimentRecordingsTabViewed',
                'reportExperimentRecordingsBucketLoaded',
                'reportExperimentRecordingsBucketFailed',
                'reportExperimentRecordingOpened',
                'reportExperimentBehaviorComparisonToggled',
                'reportExperimentBehaviorComparisonLoaded',
                'reportExperimentWatchCardSelected',
                'reportExperimentWatchHighlightOpened',
            ],
        ],
    })),
    actions({
        setSelectedVariantKey: (variantKey: string | null) => ({ variantKey }),
        setMetricSelected: (metricUuid: string, selected: boolean) => ({ metricUuid, selected }),
        setMetricFilterMode: (mode: ExperimentReplayMetricFilterMode) => ({ mode }),
        playlistFiltersChanged: (filters: RecordingUniversalFilters) => ({ filters }),
        recordingsLoaded: (recordings: ExperimentReplayRecording[]) => ({ recordings }),
        recordingOpened: (sessionId: string) => ({ sessionId }),
        toggleBehaviorComparison: true,
        selectWatchCard: (card: ExperimentWatchCardApi | null) => ({ card }),
        watchHighlightOpened: (card: ExperimentWatchCardApi, position: number) => ({ card, position }),
        prefetchSessionContexts: (sessionIds: string[]) => ({ sessionIds }),
        reportTabViewed: true,
        scannerCrossSellClicked: true,
    }),
    loaders(({ values, props, actions }) => ({
        sessionBucket: [
            null as ExperimentSessionBucket | null,
            {
                loadSessionBucket: async (_: unknown = null, breakpoint) => {
                    const request = values.sessionBucketRequest
                    if (!request) {
                        return null
                    }
                    // Debounce the checkbox churn of picking several metrics in a row.
                    await breakpoint(300)
                    // Timed here rather than from the success and failure listeners, which would
                    // have to read a start time off `cache` that a superseded request can overwrite.
                    const startedAt = performance.now()
                    let response: ExperimentSessionBucketResponseApi
                    try {
                        response = await experimentsSessionBucketsCreate(
                            String(values.currentProjectId),
                            Number(props.experiment.id),
                            request
                        )
                    } catch (error) {
                        const requestError = error as Error & { detail?: string }
                        actions.reportExperimentRecordingsBucketFailed(props.experiment.id, {
                            bucket: request.bucket,
                            metric_count: request.metric_uuids.length,
                            duration_ms: Math.round(performance.now() - startedAt),
                            error: requestError?.detail || requestError?.message || 'unknown',
                        })
                        throw error
                    }
                    // Past this breakpoint the response is the one the list will show. A superseded
                    // request throws here instead, so its load is never counted as one somebody saw.
                    // Kept outside the `try`: a cancellation must not be reported as a failure.
                    breakpoint()
                    actions.reportExperimentRecordingsBucketLoaded(props.experiment.id, {
                        bucket: request.bucket,
                        metric_count: request.metric_uuids.length,
                        session_count: response.session_ids.length,
                        truncated: response.truncated,
                        considered_metric_count: response.considered_metrics.length,
                        excluded_metric_count: response.excluded_metrics.length,
                        duration_ms: Math.round(performance.now() - startedAt),
                    })
                    return { request, response }
                },
            },
        ],
        sessionEventDeltas: [
            null as ExperimentSessionEventDeltaResponseApi | null,
            {
                loadSessionEventDeltas: async (_: unknown = null, breakpoint) => {
                    const response = await experimentsSessionEventDeltasCreate(
                        String(values.currentProjectId),
                        Number(props.experiment.id)
                    )
                    breakpoint()
                    return response
                },
            },
        ],
        linkedScanners: [
            [] as LinkedScanner[],
            {
                // The scanners already watching this experiment. The `experiment_id` filter is gated
                // on the caller's experiment access server-side, so an unreadable experiment resolves
                // to an empty list. Fail-soft to []: the tab must render even if the lookup fails.
                loadLinkedScanners: async (_: unknown = null, breakpoint) => {
                    try {
                        const response = await visionScannersList(String(values.currentProjectId), {
                            experiment_id: String(props.experiment.id),
                        })
                        breakpoint()
                        return response.results.map((scanner) => ({
                            id: scanner.id,
                            name: scanner.name,
                            scannerType: scanner.scanner_type,
                            observationsThisMonth: scanner.observations_this_month,
                        }))
                    } catch {
                        return []
                    }
                },
            },
        ],
    })),
    reducers({
        // null = "All" (every exposed session, regardless of variant). Persisted (keyed per
        // experiment via the logic path) so the facet stays in step with the playlist across tab
        // switches — the playlist persists its own filters and rehydrates them on remount.
        selectedVariantKey: [
            null as string | null,
            { persist: true },
            {
                setSelectedVariantKey: (_, { variantKey }) => variantKey,
                // A card's recordings are one variant's, so the facet moves with it — visibly, so
                // nothing narrows unannounced. Here rather than from a listener dispatching
                // setSelectedVariantKey, which would let that action stay the user's own and so
                // able to clear the card below without clearing the one just selected.
                selectWatchCard: (state: string | null, { card }) => (card ? card.variant : state),
            },
        ],
        // Empty = no metric filter. Every selected metric narrows the playlist further (AND) —
        // OR across metrics is inexpressible, since the recordings query carries a single
        // operator shared with the exposure filter. Persisted for the same reason as the
        // variant facet.
        selectedMetricUuids: [
            [] as string[],
            { persist: true },
            {
                setMetricSelected: (state: string[], { metricUuid, selected }) =>
                    selected
                        ? [...state.filter((uuid) => uuid !== metricUuid), metricUuid]
                        : state.filter((uuid) => uuid !== metricUuid),
                // Cleared alongside the mode reset below. Carrying a selection through would invert
                // what it meant: "didn't fire this metric" would silently become "fired it".
                selectWatchCard: (state, { card }) => (card ? [] : state),
            },
        ],
        // Persisted with the facets it composes with. 'fired_all' keeps the client-side event
        // filters; the other modes hand the list over to the bucket endpoint.
        metricFilterMode: [
            'fired_all' as ExperimentReplayMetricFilterMode,
            { persist: true },
            {
                setMetricFilterMode: (_, { mode }) => mode,
                // A bucket answers its own question with a capped session set, which would fight the
                // card's own session set. Reset here rather than from a listener: dispatching
                // setMetricFilterMode would clear the card this action just selected.
                selectWatchCard: (state, { card }) =>
                    card ? ('fired_all' as ExperimentReplayMetricFilterMode) : state,
            },
        ],
        // The playlist's most recently loaded page, kept so opening a recording can re-warm
        // the rest of the page's contexts, and so the watch cards can describe the recordings they
        // name without asking the server for what the list already holds.
        loadedRecordings: [
            [] as ExperimentReplayRecording[],
            {
                recordingsLoaded: (_, { recordings }) => recordings,
            },
        ],
        // A failed bucket must not silently fall back to the unbucketed list: the label would
        // then describe a population the list isn't showing. The message is kept because a
        // rejected request is usually actionable ("takes exactly one funnel metric") — a generic
        // failure line hides that from the user and the cause from us.
        sessionBucketError: [
            null as string | null,
            {
                loadSessionBucket: () => null,
                loadSessionBucketSuccess: () => null,
                loadSessionBucketFailure: (_, { error, errorObject }) => errorObject?.detail || error || 'unknown',
            },
        ],
        // The comparison is the heaviest read on this tab, so it is opened rather than loaded with
        // the tab. Not persisted: reopening the tab shouldn't silently re-run it.
        behaviorComparisonOpen: [
            false,
            {
                toggleBehaviorComparison: (open: boolean) => !open,
            },
        ],
        // Same discipline as the bucket error: a failed comparison must not fall through to an
        // empty list, which would read as "the variants behaved the same".
        sessionEventDeltasError: [
            null as string | null,
            {
                loadSessionEventDeltas: () => null,
                loadSessionEventDeltasSuccess: () => null,
                loadSessionEventDeltasFailure: (_, { error, errorObject }) => errorObject?.detail || error || 'unknown',
            },
        ],
        // The card whose recordings the playlist is showing, kept apart from the metric
        // selection: its session set comes from the shelf rather than from the experiment's
        // metrics.
        selectedWatchCard: [
            null as ExperimentWatchCardApi | null,
            {
                selectWatchCard: (_, { card }) => card,
                // Any facet the user moves themselves replaces the question the list answers, so
                // the two never stack. Left stacked they don't compose, they contradict: a card's
                // ids are one variant's and AND to an empty list under another, while a metric
                // picked on top is dropped from the query but still reads as applied in the
                // trigger and the caption.
                setMetricFilterMode: () => null,
                setSelectedVariantKey: () => null,
                setMetricSelected: () => null,
                // Closing the shelf takes away the only way to deselect, so the list would stay
                // narrowed with nothing on screen saying why.
                toggleBehaviorComparison: () => null,
            },
        ],
    }),
    selectors({
        loadedRecordingsById: [
            (s) => [s.loadedRecordings],
            (loadedRecordings: ExperimentReplayRecording[]): Map<string, ExperimentReplayRecording> =>
                new Map(loadedRecordings.map((recording) => [recording.id, recording])),
        ],
        variantKeys: [
            () => [(_, props) => props.experiment],
            (experiment: Experiment): string[] => getExperimentVariants(experiment).map((variant) => variant.key),
        ],
        behaviorComparisonAvailable: [
            (s) => [s.featureFlags],
            (featureFlags: FeatureFlagsSet): boolean => !!featureFlags[FEATURE_FLAGS.EXPERIMENT_BEHAVIOR_COMPARISON],
        ],
        effectiveVariantKey: [
            (s) => [s.selectedVariantKey, s.variantKeys],
            (selectedVariantKey: string | null, variantKeys: string[]): string | null =>
                selectedVariantKey !== null && variantKeys.includes(selectedVariantKey) ? selectedVariantKey : null,
        ],
        // Every uuid-carrying metric: inline primary + secondary, then saved/shared metrics (their
        // definition lives in `saved_metrics[].query`) — the same set the backend
        // `resolve_metric_events` scans, deduped by uuid so a shared metric linked more than once
        // shows one option. Metrics without a uuid are skipped, as the backend does: the selection
        // persists across remounts, and any positional stand-in id could re-attach it to a
        // different metric after the metric list is edited. A metric is unlinkable when every one
        // of its sources is a never-session-linked event, or when it yields no session filter at
        // all (a retention metric, or one measured only in the data warehouse) — either way its
        // filter could only match zero sessions. Those stay listed with their reason rather than
        // vanishing, which reads as the metric having been forgotten. Fails open while the check
        // loads.
        metricOptions: [
            (s) => [s.linkabilityLoaded, s.unlinkableEventNames, (_, props) => props.experiment],
            (
                linkabilityLoaded: boolean,
                unlinkableEventNames: Set<string>,
                experiment: Experiment
            ): ExperimentReplayMetricOption[] => {
                const inlineMetrics = [...(experiment.metrics || []), ...(experiment.metrics_secondary || [])]
                const savedMetrics = ((experiment.saved_metrics || []) as ExperimentSavedMetric[]).map(
                    (saved) => saved.query
                )
                const seenUuids = new Set<string>()
                return [...inlineMetrics, ...savedMetrics]
                    .filter((metric): metric is ExperimentMetric => metric?.kind === NodeKind.ExperimentMetric)
                    .flatMap((metric) =>
                        metric.uuid
                            ? [
                                  {
                                      uuid: metric.uuid,
                                      name: metric.name || getDefaultMetricTitle(metric),
                                      filters: getMetricSessionFilters(metric),
                                      dropoffReason: getFunnelDropoffReason(
                                          metric,
                                          linkabilityLoaded ? unlinkableEventNames : new Set<string>()
                                      ),
                                      eventNames: metricSourceEventNames(metric),
                                      noFilterReason: isExperimentRetentionMetric(metric)
                                          ? RETENTION_UNLINKABLE_REASON
                                          : DATA_WAREHOUSE_UNLINKABLE_REASON,
                                  },
                              ]
                            : []
                    )
                    .filter((option) => {
                        if (seenUuids.has(option.uuid)) {
                            return false
                        }
                        seenUuids.add(option.uuid)
                        return true
                    })
                    .sort(metricDisplayOrder(experiment))
                    .map(({ noFilterReason, ...option }) => {
                        const unlinkableReason =
                            option.filters.length === 0
                                ? noFilterReason
                                : linkabilityLoaded &&
                                    option.filters.every((filter) =>
                                        isUnlinkableEventFilter(filter, unlinkableEventNames)
                                    )
                                  ? METRIC_UNLINKABLE_REASON
                                  : null
                        return { ...option, unlinkable: unlinkableReason !== null, unlinkableReason }
                    })
            },
        ],
        effectiveMetricUuids: [
            (s) => [s.selectedMetricUuids, s.metricOptions, s.metricFilterMode],
            (
                selectedMetricUuids: string[],
                metricOptions: ExperimentReplayMetricOption[],
                metricFilterMode: ExperimentReplayMetricFilterMode
            ): string[] => {
                const selectable = selectedMetricUuids.filter((uuid) => {
                    const option = metricOptions.find((candidate) => candidate.uuid === uuid)
                    if (!option || option.unlinkable) {
                        return false
                    }
                    return metricFilterMode !== 'funnel_dropoff' || option.dropoffReason === null
                })
                // Selections persist across mode switches, so a mode that takes exactly one metric
                // keeps the most recently picked rather than rejecting the whole selection.
                return metricFilterMode === 'funnel_dropoff' ? selectable.slice(-1) : selectable
            },
        ],
        /**
         * Null whenever the client-side event filters express the question exactly, so the list
         * keeps its uncapped path: no metric selected, and any "fired all" of several metrics
         * (ANDing filters is the one thing a recordings query can do).
         *
         * One selected metric is the interesting case. "Fired all of it" and "fired any of it"
         * are the same question, so both take the same path — the client filter when the metric
         * counts a single event (exact and uncapped), the endpoint when it counts several. A
         * recordings query can't OR within a metric, so on a ratio or funnel the client filter
         * silently matches the primary event only.
         */
        sessionBucketRequest: [
            (s) => [s.metricFilterMode, s.effectiveMetricUuids, s.effectiveVariantKey, s.metricOptions],
            (
                metricFilterMode: ExperimentReplayMetricFilterMode,
                effectiveMetricUuids: string[],
                effectiveVariantKey: string | null,
                metricOptions: ExperimentReplayMetricOption[]
            ): ExperimentSessionBucketRequest | null => {
                const request = (bucket: ExperimentSessionBucketEnumApi): ExperimentSessionBucketRequest => ({
                    bucket,
                    metric_uuids: effectiveMetricUuids,
                    variant: effectiveVariantKey,
                })
                if (metricFilterMode === 'funnel_dropoff') {
                    return effectiveMetricUuids.length === 1 ? request('funnel_dropoff') : null
                }
                if (metricFilterMode === 'no_metric_activity') {
                    // Absence without a selection legitimately means every matchable metric.
                    return request('no_metric_activity')
                }
                if (effectiveMetricUuids.length === 0) {
                    // "Fired any of nothing" has no answer.
                    return null
                }
                if (effectiveMetricUuids.length > 1) {
                    return metricFilterMode === 'fired_any' ? request('fired_any') : null
                }
                const only = metricOptions.find((option) => option.uuid === effectiveMetricUuids[0])
                return (only?.eventNames.length ?? 0) > 1 ? request('fired_any') : null
            },
        ],
        // Undefined = no bucket, so the playlist keeps its own (uncapped) population. An empty
        // list is a real answer: nothing matched, or the request is still in flight — never a
        // silent widening to the unbucketed list.
        bucketSessionIds: [
            (s) => [s.sessionBucketRequest, s.sessionBucket, s.sessionBucketError],
            (
                sessionBucketRequest: ExperimentSessionBucketRequest | null,
                sessionBucket: ExperimentSessionBucket | null,
                sessionBucketError: string | null
            ): string[] | undefined => {
                if (!sessionBucketRequest) {
                    return undefined
                }
                if (sessionBucketError !== null || !sessionBucket) {
                    return []
                }
                // The last loaded set is kept while a new one loads, so changing a facet doesn't
                // blank the list — it is replaced once the new answer arrives.
                return sessionBucket.response.session_ids
            },
        ],
        recordingsFilters: [
            (s) => [
                s.effectiveVariantKey,
                s.effectiveMetricUuids,
                s.metricOptions,
                s.unlinkableEventNames,
                s.seenTogetherMapLoading,
                s.bucketSessionIds,
                s.selectedWatchCard,
                (_, props) => props.experiment,
            ],
            (
                effectiveVariantKey: string | null,
                effectiveMetricUuids: string[],
                metricOptions: ExperimentReplayMetricOption[],
                unlinkableEventNames: Set<string>,
                seenTogetherMapLoading: boolean,
                bucketSessionIds: string[] | undefined,
                selectedWatchCard: ExperimentWatchCardApi | null,
                experiment: Experiment
            ): RecordingUniversalFilters => {
                // The filter tree carries a single AND/OR operand (see `deriveOperand`), so
                // OR-shaped questions go to the bucket endpoint rather than into these filters.
                // Each selected metric matches on its primary event (the first session-linkable
                // source: a mean metric's event, a funnel's entry step, a ratio's numerator)
                // rather than ANDing every source, which used to require a session to fire *all*
                // funnel steps. Multiple selected metrics AND together, and each narrows.
                //
                // While the linkability check is in flight, metric filters stay out of the query:
                // a persisted selection of a metric that turns out unlinkable would otherwise fire
                // an exposure+metric query that can only be empty, flashing a false "no recordings"
                // state. Exposure-only is the correct superset until the check lands. If the check
                // *fails*, loading ends with an empty unlinkable set and the filters apply — the
                // fail-open posture every linkability consumer shares.
                const seenFilters = new Set<string>()
                const metricFilters =
                    seenTogetherMapLoading || bucketSessionIds !== undefined || selectedWatchCard !== null
                        ? // A bucket already encodes the metric condition in the session set it
                          // returns, so also ANDing the event filters would narrow it a second time.
                          []
                        : effectiveMetricUuids
                              .map((uuid) => {
                                  const linkable = (
                                      metricOptions.find((option) => option.uuid === uuid)?.filters ?? []
                                  ).filter((filter) => !isUnlinkableEventFilter(filter, unlinkableEventNames))
                                  return linkable[0]
                              })
                              .filter((filter): filter is UniversalFiltersGroupValue => {
                                  // Two metrics can share a primary event; the duplicate filter adds nothing.
                                  if (!filter || seenFilters.has(JSON.stringify(filter))) {
                                      return false
                                  }
                                  seenFilters.add(JSON.stringify(filter))
                                  return true
                              })
                return {
                    ...DEFAULT_RECORDING_FILTERS,
                    // The person-scoped filter stays in place alongside the bucket or card ids.
                    // A bucket session carries an in-session exposure event, but its person can
                    // still be outside the analysis population (excluded for seeing multiple
                    // variants, for example); the AND keeps the shown set honest to who the
                    // analysis counts. A card's recordings are pre-checked against replay
                    // existence, so unlike an event filter this list can't come back empty.
                    session_ids: selectedWatchCard ? selectedWatchCard.session_ids : bucketSessionIds,
                    // A card's sessions are picked with no duration floor, so the default "more
                    // than 5 active seconds" filter would silently drop the short ones (a rage
                    // click and an abandon can fit in less) and the list would show fewer
                    // recordings than the card promises.
                    duration: selectedWatchCard ? [] : DEFAULT_RECORDING_FILTERS.duration,
                    date_from: experiment.start_date ?? DEFAULT_RECORDING_FILTERS.date_from,
                    date_to: experiment.end_date ?? null,
                    filter_test_accounts: experiment.exposure_criteria?.filterTestAccounts ?? false,
                    // Resolved server-side from the experiment (same population the analysis
                    // counts), so it works even when exposure events are fired server-side and
                    // shows exposed users' whole journey, not just sessions containing the
                    // exposure event. Deliberately not an event filter in `filter_group`.
                    experiment_exposure:
                        typeof experiment.id === 'number'
                            ? {
                                  experiment_id: experiment.id,
                                  ...(effectiveVariantKey !== null ? { variant: effectiveVariantKey } : {}),
                              }
                            : undefined,
                    filter_group: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: FilterLogicalOperator.And,
                                values: metricFilters,
                            },
                        ],
                    },
                }
            },
        ],
    }),
    listeners(({ values, actions, cache, props }) => ({
        // Every facet the bucket is keyed on re-asks for it. Listening to the actions rather than
        // subscribing to the spec keeps this off the redux subscription path.
        setMetricFilterMode: () => {
            actions.loadSessionBucket()
        },
        setMetricSelected: () => {
            if (values.sessionBucketRequest) {
                actions.loadSessionBucket()
            }
        },
        setSelectedVariantKey: () => {
            if (values.sessionBucketRequest) {
                actions.loadSessionBucket()
            }
        },
        // The shared playlist renders its own "Showing N selected recordings · Show all" control
        // whenever session_ids are set. Clearing it there is the same intent as leaving the
        // bucket, so follow it instead of pushing the ids straight back. Only when the tab has
        // ids of its own: a mode with nothing to filter on yet (no eligible metric selected)
        // pushes no session_ids either, and reading that back as a clear would bounce the mode
        // to 'fired_all' the moment it was picked.
        playlistFiltersChanged: ({ filters }) => {
            if (
                values.metricFilterMode !== 'fired_all' &&
                filters.session_ids === undefined &&
                values.bucketSessionIds !== undefined
            ) {
                actions.setMetricFilterMode('fired_all')
            }
            // The playlist's own "Show all" control clears session_ids; when a card put them
            // there, that is the same intent as leaving the card, so follow it rather than
            // pushing the ids straight back.
            if (values.selectedWatchCard !== null && filters.session_ids == null) {
                actions.selectWatchCard(null)
            }
        },
        // Opening the panel is what runs the comparison — it is the heaviest read here, and most
        // visits to the tab don't want it. Reopening reuses what's loaded or lets a pending load
        // finish rather than firing a duplicate; the server-side cache covers a deliberate reload.
        toggleBehaviorComparison: () => {
            actions.reportExperimentBehaviorComparisonToggled(props.experiment.id, values.behaviorComparisonOpen)
            if (values.behaviorComparisonOpen && !values.sessionEventDeltas && !values.sessionEventDeltasLoading) {
                actions.loadSessionEventDeltas()
            }
        },
        loadSessionEventDeltasSuccess: ({ sessionEventDeltas }) => {
            if (!sessionEventDeltas) {
                return
            }
            // Counted through the generated enum rather than string literals, so a renamed or
            // added kind breaks the compile here instead of silently reporting zero in the
            // telemetry the evidence floors are tuned from.
            const cardsByKind = groupBy(sessionEventDeltas.cards, (card) => card.kind)
            const kindCount = (kind: ExperimentWatchCardKindEnumApi): number => cardsByKind[kind]?.length ?? 0
            actions.reportExperimentBehaviorComparisonLoaded(props.experiment.id, {
                too_early: sessionEventDeltas.too_early,
                behavior_cards: kindCount(ExperimentWatchCardKindEnumApi.Behavior),
                friction_cards: kindCount(ExperimentWatchCardKindEnumApi.Friction),
                variant_only_cards: kindCount(ExperimentWatchCardKindEnumApi.VariantOnly),
                metric_cards: kindCount(ExperimentWatchCardKindEnumApi.Metric),
                dropped_duplicate_cards: sessionEventDeltas.dropped_duplicate_cards,
            })
        },
        selectWatchCard: ({ card }) => {
            // Deselecting is already visible as the next card's selection or the toggle's close.
            if (card) {
                actions.reportExperimentWatchCardSelected(props.experiment.id, {
                    kind: card.kind,
                    strength: card.strength ?? null,
                    metric_backed: card.metric_name !== null,
                    recording_count: card.recording_count,
                    highlight_count: card.highlights.length,
                })
            }
        },
        watchHighlightOpened: ({ card, position }) => {
            actions.reportExperimentWatchHighlightOpened(props.experiment.id, {
                card_kind: card.kind,
                position,
            })
        },
        // Prefetch experiment context for the freshly loaded page of recordings, so opening
        // any of them renders the player's experiments box straight from the server-side
        // cache. A session's context is independent of the list filters (it's per
        // session + viewer), so sessions overlapping across filter changes are already warm
        // and the endpoint skips them.
        recordingsLoaded: ({ recordings }) => {
            actions.prefetchSessionContexts(recordings.map((recording) => recording.id))
        },
        // Re-warm the rest of the page whenever the user moves to another recording: the
        // server-side cache entries expire on a TTL that starts at prefetch time, so a page
        // prefetched once goes cold under a user who watches one recording for a while. The
        // endpoint skips warm sessions, so in the steady state a re-fire costs one request
        // and cache reads; only expired entries recompute. The opened recording is excluded —
        // the player is fetching it right now, and including it would compute it twice.
        recordingOpened: ({ sessionId }) => {
            actions.prefetchSessionContexts(
                values.loadedRecordings.map((recording) => recording.id).filter((id) => id !== sessionId)
            )
            actions.reportExperimentRecordingOpened(props.experiment.id, {
                variant: values.effectiveVariantKey,
                metric_filter_mode: values.metricFilterMode,
                selected_metric_count: values.effectiveMetricUuids.length,
                is_bucketed: values.bucketSessionIds !== undefined,
                watch_card_kind: values.selectedWatchCard?.kind ?? null,
            })
        },
        // Both outcomes of the linkability check report the view, since a failed check leaves the
        // tab running on its fail-open defaults rather than leaving it unusable.
        loadSeenTogetherSuccess: () => {
            actions.reportTabViewed()
        },
        loadSeenTogetherFailure: () => {
            actions.reportTabViewed()
        },
        reportTabViewed: () => {
            // The linkability logic is shared with the metrics tab's "View recordings" buttons and
            // reloads when the experiment's metrics change, so its success can arrive more than once
            // while this tab is open. A view is per tab open, and the logic unmounts with the tab.
            if (cache.reportedTabView) {
                return
            }
            cache.reportedTabView = true
            actions.reportExperimentRecordingsTabViewed(props.experiment.id, {
                variant_count: values.variantKeys.length,
                metric_count: values.metricOptions.length,
                linkable_metric_count: values.metricOptions.filter((option) => !option.unlinkable).length,
            })
        },
        scannerCrossSellClicked: () => {
            void addProductIntentForCrossSell({
                from: ProductKey.EXPERIMENTS,
                to: ProductKey.REPLAY_VISION,
                intent_context: ProductIntentContext.EXPERIMENT_CREATE_SCANNER,
            })
        },
        prefetchSessionContexts: async ({ sessionIds }, breakpoint) => {
            if (!values.featureFlags[FEATURE_FLAGS.REPLAY_EXPERIMENT_CONTEXT] || sessionIds.length === 0) {
                return
            }
            // Debounce rapid filter churn — a superseded batch is cancelled at the breakpoint.
            await breakpoint(500)
            // Serialize behind any in-flight batch: its cache writes only land when it
            // finishes, so a batch fired concurrently would recompute the same sessions
            // instead of skipping them as warm. The breakpoint drops this run if a newer
            // prefetch arrived while it waited.
            while (cache.sessionContextPrefetch) {
                await cache.sessionContextPrefetch
                breakpoint()
            }
            const request = experimentsSessionContextsCreate(String(values.currentProjectId), {
                session_ids: sessionIds.slice(0, SESSION_CONTEXT_PREFETCH_LIMIT),
            }).catch(() => {
                // Best-effort prefetch — the player's own request is the fallback.
            })
            cache.sessionContextPrefetch = request
            try {
                await request
            } finally {
                cache.sessionContextPrefetch = null
            }
        },
    })),
    afterMount(({ values, actions }) => {
        actions.setDefaultTab(SessionRecordingSidebarTab.OVERVIEW)
        // Only the vision entry point renders the watching-scanners card, so don't spend the lookup
        // for everyone else who opens this tab without the flag.
        if (values.featureFlags[FEATURE_FLAGS.VISION_ENTRYPOINT_EXPERIMENTS]) {
            actions.loadLinkedScanners()
        }

        // The mode persists, so a tab reopened in a bucket needs its session set again.
        if (values.sessionBucketRequest) {
            actions.loadSessionBucket()
        }

        // The linkability check is shared with the metrics tab, so it can already have settled —
        // loaded, or failed with no reload coming — before this tab is opened, in which case no
        // load action follows to report the view off. A check started by this mount is already
        // loading here, so it reports from the load listeners instead; a prior failure reports
        // the fail-open defaults, the same posture as a failure that lands while the tab is open.
        if (values.linkabilityLoaded || !values.seenTogetherMapLoading) {
            actions.reportTabViewed()
        }

        // Opening the tab is a session-replay cross-sell from experiments.
        void addProductIntentForCrossSell({
            from: ProductKey.EXPERIMENTS,
            to: ProductKey.SESSION_REPLAY,
            intent_context: ProductIntentContext.EXPERIMENT_VIEW_RECORDINGS,
        })
    }),
    // The sidebar singleton normally unmounts alongside this logic and resets itself; this covers the
    // case where another player keeps it mounted, so the experiment default doesn't leak to it.
    beforeUnmount(({ actions }) => {
        actions.setDefaultTab(SessionRecordingSidebarTab.INSPECTOR)
    }),
])
