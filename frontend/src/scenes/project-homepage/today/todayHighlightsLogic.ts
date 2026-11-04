import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog, { type CaptureOptions } from 'posthog-js'
import { v4 as uuidv4 } from 'uuid'

import { toast } from '@posthog/quill'

import { ApiError } from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import type { InsightShortId } from '~/types'

import { insightsList } from 'products/product_analytics/frontend/generated/api'
import {
    todayHighlightsRetrieve,
    todayPulsePinsRetrieve,
    todayPulsePinsUpdate,
} from 'products/today/frontend/generated/api'
import type {
    HighlightItemApi,
    HighlightMetricApi,
    HighlightsApi,
    PulsePinApi,
    PulseSlotApi,
} from 'products/today/frontend/generated/api.schemas'

export const HIGHLIGHTS_POLL_MS = 2_000
const HIGHLIGHTS_WAIT_MS = 2_000
const PULSE_SEARCH_DEBOUNCE_MS = 200
const PINS_LOAD_RETRY_MS = 5_000
const PINS_LOAD_RETRIES = 3
const PIN_SEARCH_RESULTS = 20
const PINNABLE_DISPLAYS = 'ActionsLineGraph,ActionsBar,ActionsStackedBar,ActionsAreaGraph'
export const PULSE_TILES = 4
const PULSE_SLOW_MS = 30_000

interface PulseLoad {
    id: string
    startedAt: number
    firstCardAt: number | null
    firstResponseAt: number | null
    loadingMode: 'progressive' | 'complete' | null
    firstNumberAt: number | null
    requestCount: number
    responseCount: number
    errorCount: number
    initialStatus: HighlightsApi['status'] | null
    contentAtMount: boolean
    startedVisible: boolean
    wasHidden: boolean
    finished: boolean
}

function pulseLoadOutcome(
    status: HighlightsApi['status'] | undefined,
    failed: boolean,
    unavailable: boolean,
    numberCount: number
): 'request_error' | 'unavailable' | 'failed' | 'ready' | 'empty' | null {
    if (failed) {
        return 'request_error'
    }
    if (unavailable) {
        return 'unavailable'
    }
    if (status === 'failed') {
        return 'failed'
    }
    return status === 'ready' ? (numberCount > 0 ? 'ready' : 'empty') : null
}

function capturePulseLoad(
    event: string,
    load: PulseLoad,
    properties: Record<string, unknown> = {},
    options?: CaptureOptions
): void {
    const payload = {
        load_id: load.id,
        duration_ms: Math.round(performance.now() - load.startedAt),
        first_card_duration_ms: load.firstCardAt === null ? null : Math.round(load.firstCardAt - load.startedAt),
        first_response_duration_ms:
            load.firstResponseAt === null ? null : Math.round(load.firstResponseAt - load.startedAt),
        loading_mode: load.loadingMode,
        first_number_duration_ms: load.firstNumberAt === null ? null : Math.round(load.firstNumberAt - load.startedAt),
        request_count: load.requestCount,
        response_count: load.responseCount,
        error_count: load.errorCount,
        initial_status: load.initialStatus,
        content_at_mount: load.contentAtMount,
        started_visible: load.startedVisible,
        was_hidden: load.wasHidden,
        visible: document.visibilityState === 'visible',
        ...properties,
    }
    if (options) {
        posthog.capture(event, payload, options)
    } else {
        posthog.capture(event, payload)
    }
}

export type PulsePinSource = 'editor' | 'hover_card'

export function pulsePinLimitReason(pinnedCount: number, pinned: boolean): string | undefined {
    return pinnedCount >= PULSE_TILES && !pinned ? `You can pin ${PULSE_TILES}. Unpin one first.` : undefined
}

function pinnedSlot(pin: PulsePinApi, highlights: HighlightsApi | null): PulseSlotApi {
    const shortId = pin.key.startsWith('insight:') ? pin.key.slice('insight:'.length) : null
    return {
        key: pin.key,
        name: pin.name,
        url: shortId ? urls.insightView(shortId as InsightShortId) : null,
        interval: null,
        status:
            highlights?.pins.find((highlightPin) => highlightPin.key === pin.key)?.status === 'unavailable'
                ? 'error'
                : 'pending',
    }
}

export interface PulsePlace {
    key: string
    standIn: string | null
}

export interface PulsePlacement {
    slots: PulseSlotApi[]
    places: PulsePlace[]
}

export function pulseSlotsOf(highlights: HighlightsApi | null): PulseSlotApi[] {
    return (
        highlights?.pulse_slots ??
        (highlights?.pulse ?? []).map((metric) => ({
            key: metric.key,
            name: metric.name,
            url: metric.url,
            interval: metric.interval,
            status: 'ready',
        }))
    )
}

function needsStandIn(place: PulsePlace, present: boolean, isHidden: (key: string) => boolean): boolean {
    return present ? isHidden(place.key) : place.standIn !== null
}

export function placePulseSlots(
    slots: PulseSlotApi[],
    places: PulsePlace[],
    isHidden: (key: string) => boolean,
    limit: number = PULSE_TILES
): PulsePlacement {
    const byKey = new Map(slots.map((slot) => [slot.key, slot]))
    const kept = places.slice(0, limit)
    const claimed = new Set(
        kept
            .flatMap((place) => [place.key, ...(place.standIn !== null ? [place.standIn] : [])])
            .filter((key) => byKey.has(key))
    )
    const spare = slots.filter((slot) => !claimed.has(slot.key) && !isHidden(slot.key))
    const used = new Set<string>()
    const take = (key: string | null): PulseSlotApi | undefined => {
        const slot = key !== null ? byKey.get(key) : undefined
        if (slot && !isHidden(slot.key) && !used.has(slot.key)) {
            used.add(slot.key)
            return slot
        }
        const next = spare.shift()
        if (next) {
            used.add(next.key)
        }
        return next
    }
    const shown: PulseSlotApi[] = []
    const nextPlaces: PulsePlace[] = []
    for (const place of kept) {
        if (needsStandIn(place, byKey.has(place.key), isHidden)) {
            const standIn = take(place.standIn)
            if (standIn) {
                shown.push(standIn)
            }
            nextPlaces.push({ key: place.key, standIn: standIn?.key ?? null })
            continue
        }
        const slot = take(byKey.has(place.key) ? place.key : null)
        if (slot) {
            shown.push(slot)
            nextPlaces.push({ key: slot.key, standIn: null })
        }
    }
    for (const slot of spare.slice(0, limit - nextPlaces.length)) {
        shown.push(slot)
        nextPlaces.push({ key: slot.key, standIn: null })
    }
    return { slots: shown, places: nextPlaces }
}

function pulseKind(key: string): 'insight' | 'key_metric' {
    return key.startsWith('insight:') ? 'insight' : 'key_metric'
}

function hiddenHighlightKey(projectId: number | string, key: string): string {
    return `${projectId}:${key}`
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface todayHighlightsLogicValues {
    currentProjectId: number | string // teamLogic
    doneHighlightKeys: string[]
    forYouHighlights: HighlightItemApi[]
    hiddenHighlights: Record<string, string>
    hiddenPulseMetrics: Record<string, true>
    highlights: HighlightsApi | null
    highlightsFailed: boolean
    highlightsHiddenNow: string[]
    highlightsLoading: boolean
    highlightsPending: boolean
    highlightsWaitOver: boolean
    pulseInsightResults: PulsePinApi[]
    pulseInsightResultsLoading: boolean
    pulseInsightSearchFailed: boolean
    pulsePending: boolean
    pulsePins: PulsePinApi[]
    pulsePinsLoadFailed: boolean
    pulsePinsLoaded: boolean
    pulsePinsLoading: boolean
    pulsePinsSaving: boolean
    pulsePinsSettled: boolean
    pulsePinsUnavailableReason: string | null
    pulsePlacement: PulsePlacement
    pulsePlaces: PulsePlace[]
    pulseSlots: PulseSlotApi[]
    pulseTiles: HighlightMetricApi[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface todayHighlightsLogicActions {
    hideHighlight: (
        item: HighlightItemApi,
        position: number
    ) => {
        item: HighlightItemApi
        position: number
    }
    hidePulseMetric: (
        metric: HighlightMetricApi,
        position: number
    ) => {
        metric: HighlightMetricApi
        position: number
    }
    highlightOpened: (
        item: HighlightItemApi,
        position: number
    ) => {
        item: HighlightItemApi
        position: number
    }
    loadHighlights: (refresh?: boolean) => boolean
    loadHighlightsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadHighlightsSuccess: (
        highlights: HighlightsApi | null,
        payload?: boolean
    ) => {
        highlights: HighlightsApi | null
        payload?: boolean
    }
    loadPulseInsightResults: (search: string) => string
    loadPulseInsightResultsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPulseInsightResultsSuccess: (
        pulseInsightResults: PulsePinApi[],
        payload?: string
    ) => {
        pulseInsightResults: PulsePinApi[]
        payload?: string
    }
    loadPulsePins: () => any
    loadPulsePinsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPulsePinsSuccess: (
        pulsePins: PulsePinApi[],
        payload?: any
    ) => {
        pulsePins: PulsePinApi[]
        payload?: any
    }
    pulseEditorOpened: () => {
        value: true
    }
    pulseMetricOpened: (
        metric: HighlightMetricApi,
        position: number
    ) => {
        metric: HighlightMetricApi
        position: number
    }
    pulseMetricPreviewed: (
        metric: HighlightMetricApi,
        position: number
    ) => {
        metric: HighlightMetricApi
        position: number
    }
    pulsePinsLoadGaveUp: () => {
        value: true
    }
    pulsePinsSaved: () => {
        value: true
    }
    pulseViewMounted: (sample: boolean) => {
        sample: boolean
    }
    pulseViewUnmounted: (documentDeparture?: boolean) => {
        documentDeparture: boolean
    }
    pulseViewUpdated: () => {
        value: true
    }
    retryPulse: () => {
        value: true
    }
    setHiddenHighlights: (hidden: Record<string, string>) => {
        hidden: Record<string, string>
    }
    setHiddenPulseMetrics: (hidden: Record<string, true>) => {
        hidden: Record<string, true>
    }
    setPinnedPulseKeys: (metrics: PulsePinApi[]) => {
        metrics: PulsePinApi[]
    }
    setPulsePlaces: (places: PulsePlace[]) => {
        places: PulsePlace[]
    }
    stopWaitingForHighlights: () => {
        value: true
    }
    togglePulsePin: (
        pin: PulsePinApi,
        source: PulsePinSource
    ) => {
        pin: PulsePinApi
        source: PulsePinSource
    }
    unhideHighlight: (
        item: HighlightItemApi,
        position: number
    ) => {
        item: HighlightItemApi
        position: number
    }
    unhidePulseMetric: (
        metric: HighlightMetricApi,
        position: number
    ) => {
        metric: HighlightMetricApi
        position: number
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface todayHighlightsLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        pulsePinsUnavailableReason: (
            pulsePinsLoaded: boolean,
            pulsePinsLoadFailed: boolean,
            pulsePinsSaving: boolean
        ) => string | null
        pulsePinsSettled: (pulsePinsLoaded: boolean, pulsePinsLoadFailed: boolean) => boolean
        pulsePlacement: (
            pulsePins: PulsePinApi[],
            highlights: HighlightsApi | null,
            hiddenPulseMetrics: Record<string, true>,
            currentProjectId: number | string,
            pulsePlaces: any,
            pulsePinsSettled: boolean
        ) => PulsePlacement
        pulseSlots: (pulsePlacement: any, highlights: HighlightsApi | null, highlightsFailed: boolean) => PulseSlotApi[]
        pulseTiles: (highlights: HighlightsApi | null, pulseSlots: PulseSlotApi[]) => HighlightMetricApi[]
        highlightsPending: (
            highlights: HighlightsApi | null,
            highlightsLoading: boolean,
            highlightsFailed: boolean
        ) => boolean
        pulsePending: (
            highlights: HighlightsApi | null,
            highlightsPending: boolean,
            pulseSlots: PulseSlotApi[],
            highlightsFailed: boolean,
            pulsePinsSettled: boolean
        ) => boolean
        doneHighlightKeys: (
            highlights: HighlightsApi | null,
            hiddenHighlights: Record<string, string>,
            highlightsHiddenNow: string[],
            currentProjectId: number | string
        ) => string[]
        forYouHighlights: (
            highlights: HighlightsApi | null,
            hiddenHighlights: Record<string, string>,
            doneHighlightKeys: string[],
            currentProjectId: number | string
        ) => HighlightItemApi[]
    }
}

export type todayHighlightsLogicType = MakeLogicType<
    todayHighlightsLogicValues,
    todayHighlightsLogicActions,
    Record<string, any>,
    todayHighlightsLogicMeta
>

export const todayHighlightsLogic = kea<todayHighlightsLogicType>([
    path(['scenes', 'project-homepage', 'today', 'todayHighlightsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),
    actions({
        highlightOpened: (item: HighlightItemApi, position: number) => ({ item, position }),
        pulseMetricOpened: (metric: HighlightMetricApi, position: number) => ({ metric, position }),
        pulseMetricPreviewed: (metric: HighlightMetricApi, position: number) => ({ metric, position }),
        hideHighlight: (item: HighlightItemApi, position: number) => ({ item, position }),
        unhideHighlight: (item: HighlightItemApi, position: number) => ({ item, position }),
        setHiddenHighlights: (hidden: Record<string, string>) => ({ hidden }),
        stopWaitingForHighlights: true,
        hidePulseMetric: (metric: HighlightMetricApi, position: number) => ({ metric, position }),
        unhidePulseMetric: (metric: HighlightMetricApi, position: number) => ({ metric, position }),
        setHiddenPulseMetrics: (hidden: Record<string, true>) => ({ hidden }),
        setPinnedPulseKeys: (metrics: PulsePinApi[]) => ({ metrics }),
        pulsePinsSaved: true,
        pulseEditorOpened: true,
        togglePulsePin: (pin: PulsePinApi, source: PulsePinSource) => ({ pin, source }),
        pulsePinsLoadGaveUp: true,
        setPulsePlaces: (places: PulsePlace[]) => ({ places }),
        pulseViewMounted: (sample: boolean) => ({ sample }),
        pulseViewUpdated: true,
        retryPulse: true,
        pulseViewUnmounted: (documentDeparture: boolean = false) => ({ documentDeparture }),
    }),
    loaders(({ values, cache }) => ({
        pulseInsightResults: [
            [] as PulsePinApi[],
            {
                loadPulseInsightResults: async (search: string, breakpoint) => {
                    await breakpoint(PULSE_SEARCH_DEBOUNCE_MS)
                    const { results } = await insightsList(String(values.currentProjectId), {
                        basic: true,
                        saved: true,
                        display: PINNABLE_DISPLAYS,
                        search,
                        order: '-last_viewed_at',
                        limit: PIN_SEARCH_RESULTS,
                    })
                    breakpoint()
                    return results.map(
                        (insight): PulsePinApi => ({
                            key: `insight:${insight.short_id}`,
                            name: insight.name || insight.derived_name || 'Untitled insight',
                            dashboard_id: null,
                        })
                    )
                },
            },
        ],
        pulsePins: [
            [] as PulsePinApi[],
            {
                loadPulsePins: async (): Promise<PulsePinApi[]> => {
                    const edits = cache.pinEdits ?? 0
                    try {
                        const { pins } = await todayPulsePinsRetrieve(String(values.currentProjectId))
                        return (cache.pinEdits ?? 0) === edits ? pins : values.pulsePins
                    } catch (error) {
                        if (error instanceof ApiError && error.status === 404) {
                            return []
                        }
                        throw error
                    }
                },
            },
        ],
        highlights: [
            null as HighlightsApi | null,
            {
                loadHighlights: async (refresh: boolean = false): Promise<HighlightsApi | null> => {
                    if (values.currentProjectId === null) {
                        return null
                    }
                    try {
                        return refresh
                            ? await todayHighlightsRetrieve(String(values.currentProjectId), { refresh: true })
                            : await todayHighlightsRetrieve(String(values.currentProjectId))
                    } catch (error) {
                        if (error instanceof ApiError && error.status === 404) {
                            return null
                        }
                        throw error
                    }
                },
            },
        ],
    })),
    reducers({
        pulsePins: {
            setPinnedPulseKeys: (_, { metrics }) => metrics,
        },
        pulsePinsLoaded: [false, { loadPulsePinsSuccess: () => true }],
        pulsePinsLoadFailed: [false, { pulsePinsLoadGaveUp: () => true, loadPulsePinsSuccess: () => false }],
        pulsePinsSaving: [false, { setPinnedPulseKeys: () => true, pulsePinsSaved: () => false }],
        pulseInsightSearchFailed: [
            false,
            { loadPulseInsightResults: () => false, loadPulseInsightResultsFailure: () => true },
        ],
        pulsePlaces: [
            [] as PulsePlace[],
            {
                setPulsePlaces: (_, { places }) => places,
            },
        ],
        hiddenHighlights: [
            {} as Record<string, string>,
            { persist: true },
            { setHiddenHighlights: (_, { hidden }) => hidden },
        ],
        hiddenPulseMetrics: [
            {} as Record<string, true>,
            { persist: true },
            { setHiddenPulseMetrics: (_, { hidden }) => hidden },
        ],
        highlightsHiddenNow: [
            [] as string[],
            {
                hideHighlight: (state, { item }) => [...state, item.key],
                unhideHighlight: (state, { item }) => state.filter((key) => key !== item.key),
            },
        ],
        highlightsWaitOver: [false, { stopWaitingForHighlights: () => true }],
        highlightsFailed: [
            false,
            {
                loadHighlights: () => false,
                loadHighlightsFailure: () => true,
            },
        ],
        highlights: {
            loadHighlightsFailure: (state) => state,
        },
    }),
    selectors({
        pulsePinsUnavailableReason: [
            (s) => [s.pulsePinsLoaded, s.pulsePinsLoadFailed, s.pulsePinsSaving],
            (pulsePinsLoaded: boolean, pulsePinsLoadFailed: boolean, pulsePinsSaving: boolean): string | null =>
                pulsePinsSaving
                    ? 'Saving your pins…'
                    : pulsePinsLoadFailed
                      ? "Couldn't load your pins. Reload the page to try again."
                      : pulsePinsLoaded
                        ? null
                        : 'Loading your pins…',
        ],
        pulsePinsSettled: [
            (s) => [s.pulsePinsLoaded, s.pulsePinsLoadFailed],
            (pulsePinsLoaded: boolean, pulsePinsLoadFailed: boolean): boolean => pulsePinsLoaded || pulsePinsLoadFailed,
        ],
        pulsePlacement: [
            (s) => [
                s.pulsePins,
                s.highlights,
                s.hiddenPulseMetrics,
                s.currentProjectId,
                s.pulsePlaces,
                s.pulsePinsSettled,
            ],
            (
                pulsePins: PulsePinApi[],
                highlights: HighlightsApi | null,
                hiddenPulseMetrics: Record<string, true>,
                currentProjectId: number | string,
                pulsePlaces: PulsePlace[],
                pulsePinsSettled: boolean
            ): PulsePlacement => {
                // Pins decide the order, so numbers wait for them rather than move after they arrive.
                if (!pulsePinsSettled) {
                    return { slots: [], places: pulsePlaces }
                }
                const slots = pulseSlotsOf(highlights)
                const pinnedKeys = new Set(pulsePins.map((pin) => pin.key))
                const pinned = pulsePins
                    .slice(0, PULSE_TILES)
                    .map((pin) => slots.find((slot) => slot.key === pin.key) ?? pinnedSlot(pin, highlights))
                const suggested = placePulseSlots(
                    slots.filter((slot) => !pinnedKeys.has(slot.key)),
                    pulsePlaces.filter((place) => !pinnedKeys.has(place.key)),
                    (key) => !!hiddenPulseMetrics[hiddenHighlightKey(currentProjectId, key)],
                    PULSE_TILES - pinned.length
                )
                return { slots: [...pinned, ...suggested.slots], places: suggested.places }
            },
        ],
        pulseSlots: [
            (s) => [s.pulsePlacement, s.highlights, s.highlightsFailed],
            (
                pulsePlacement: PulsePlacement,
                highlights: HighlightsApi | null,
                highlightsFailed: boolean
            ): PulseSlotApi[] =>
                pulsePlacement.slots.map(
                    (slot): PulseSlotApi =>
                        (highlightsFailed || highlights?.status === 'failed') && slot.status === 'pending'
                            ? { ...slot, status: 'error' }
                            : slot
                ),
        ],
        pulseTiles: [
            (s) => [s.highlights, s.pulseSlots],
            (highlights: HighlightsApi | null, pulseSlots: PulseSlotApi[]): HighlightMetricApi[] =>
                pulseSlots.flatMap((slot) => highlights?.pulse.find((metric) => metric.key === slot.key) ?? []),
        ],
        highlightsPending: [
            (s) => [s.highlights, s.highlightsLoading, s.highlightsFailed],
            (highlights: HighlightsApi | null, highlightsLoading: boolean, highlightsFailed: boolean): boolean =>
                !highlightsFailed &&
                (highlights
                    ? highlights.status === 'computing' && highlights.generated_at === null
                    : highlightsLoading),
        ],
        pulsePending: [
            (s) => [s.highlights, s.highlightsPending, s.pulseSlots, s.highlightsFailed, s.pulsePinsSettled],
            (
                highlights: HighlightsApi | null,
                highlightsPending: boolean,
                pulseSlots: PulseSlotApi[],
                highlightsFailed: boolean,
                pulsePinsSettled: boolean
            ): boolean =>
                !highlightsFailed &&
                pulseSlots.length === 0 &&
                (!pulsePinsSettled || highlightsPending || highlights?.status === 'computing'),
        ],
        doneHighlightKeys: [
            (s) => [s.highlights, s.hiddenHighlights, s.highlightsHiddenNow, s.currentProjectId],
            (
                highlights: HighlightsApi | null,
                hiddenHighlights: Record<string, string>,
                highlightsHiddenNow: string[],
                currentProjectId: number | string
            ): string[] =>
                highlightsHiddenNow.filter(
                    (key) => hiddenHighlights[hiddenHighlightKey(currentProjectId, key)] === highlights?.day
                ),
        ],
        forYouHighlights: [
            (s) => [s.highlights, s.hiddenHighlights, s.doneHighlightKeys, s.currentProjectId],
            (
                highlights: HighlightsApi | null,
                hiddenHighlights: Record<string, string>,
                doneHighlightKeys: string[],
                currentProjectId: number | string
            ): HighlightItemApi[] =>
                (highlights?.items ?? []).filter(
                    (item) =>
                        hiddenHighlights[hiddenHighlightKey(currentProjectId, item.key)] !== highlights?.day ||
                        doneHighlightKeys.includes(item.key)
                ),
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        pulseViewMounted: ({ sample }) => {
            actions.setPulsePlaces([])
            actions.setPulsePlaces(values.pulsePlacement.places)
            if (sample) {
                return
            }
            const load: PulseLoad = {
                id: uuidv4(),
                startedAt: performance.now(),
                firstCardAt: null,
                firstResponseAt: null,
                loadingMode: null,
                firstNumberAt: null,
                requestCount: values.highlightsLoading ? 1 : 0,
                responseCount: 0,
                errorCount: 0,
                initialStatus: values.highlights?.status ?? null,
                contentAtMount: values.highlights?.generated_at !== null && values.highlights !== null,
                startedVisible: document.visibilityState === 'visible',
                wasHidden: document.visibilityState !== 'visible',
                finished: false,
            }
            cache.pulseLoad = load
            capturePulseLoad('today pulse load started', load)
            cache.disposables.add(
                () => {
                    const onPageHide = (): void => actions.pulseViewUnmounted(true)
                    const onPageShow = (event: PageTransitionEvent): void => {
                        if (event.persisted) {
                            actions.pulseViewMounted(sample)
                            actions.pulseViewUpdated()
                        }
                    }
                    window.addEventListener('pagehide', onPageHide)
                    window.addEventListener('pageshow', onPageShow)
                    return () => {
                        window.removeEventListener('pagehide', onPageHide)
                        window.removeEventListener('pageshow', onPageShow)
                    }
                },
                'pulseLoadPageLifecycle',
                { pauseOnPageHidden: false }
            )
            cache.disposables.add(
                () => {
                    const onVisibilityChange = (): void => {
                        load.wasHidden ||= document.visibilityState !== 'visible'
                    }
                    document.addEventListener('visibilitychange', onVisibilityChange)
                    return () => document.removeEventListener('visibilitychange', onVisibilityChange)
                },
                'pulseLoadVisibility',
                { pauseOnPageHidden: false }
            )
            cache.disposables.add(
                () => {
                    const timer = window.setTimeout(() => {
                        if (!load.finished) {
                            capturePulseLoad('today pulse load slow', load)
                        }
                    }, PULSE_SLOW_MS)
                    return () => clearTimeout(timer)
                },
                'pulseLoadSlow',
                { pauseOnPageHidden: false }
            )
        },
        pulseViewUpdated: () => {
            const load = cache.pulseLoad as PulseLoad | undefined
            if (!load || load.finished) {
                return
            }
            if (values.pulseSlots.length > 0 && load.firstCardAt === null) {
                load.firstCardAt = performance.now()
            }
            const numberCount = values.highlightsPending ? 0 : values.pulseTiles.length
            if (numberCount > 0 && load.firstNumberAt === null) {
                load.firstNumberAt = performance.now()
                capturePulseLoad('today pulse first number shown', load, { number_count: numberCount })
            }
            const outcome = pulseLoadOutcome(
                values.highlights?.status,
                values.highlightsFailed,
                cache.highlightsUnavailable === true,
                numberCount
            )
            if (outcome) {
                load.finished = true
                cache.disposables.dispose('pulseLoadSlow')
                cache.disposables.dispose('pulseLoadVisibility')
                capturePulseLoad('today pulse load finished', load, {
                    outcome,
                    number_count: numberCount,
                    pending_count: values.pulseSlots.filter((slot) => slot.status === 'pending').length,
                })
            }
        },
        pulseViewUnmounted: ({ documentDeparture }) => {
            const load = cache.pulseLoad as PulseLoad | undefined
            if (load && !load.finished) {
                load.finished = true
                capturePulseLoad(
                    'today pulse load finished',
                    load,
                    { outcome: 'abandoned' },
                    documentDeparture ? { transport: 'sendBeacon', send_instantly: true } : undefined
                )
            }
            cache.disposables.dispose('pulseLoadSlow')
            cache.disposables.dispose('pulseLoadVisibility')
            if (!documentDeparture) {
                cache.disposables.dispose('pulseLoadPageLifecycle')
            }
            delete cache.pulseLoad
        },
        loadHighlights: () => {
            cache.highlightsUnavailable = false
            const load = cache.pulseLoad as PulseLoad | undefined
            if (load && !load.finished) {
                load.requestCount += 1
            }
        },
        loadHighlightsFailure: () => {
            const load = cache.pulseLoad as PulseLoad | undefined
            if (load && !load.finished) {
                load.errorCount += 1
            }
        },
        setPinnedPulseKeys: async ({ metrics }, breakpoint) => {
            actions.setPulsePlaces(values.pulsePlacement.places)
            cache.pinEdits = (cache.pinEdits ?? 0) + 1
            const previous: Promise<unknown> = cache.pinsSave ?? Promise.resolve()
            const save = (cache.pinsSave = previous
                .catch(() => undefined)
                .then(() => todayPulsePinsUpdate(String(values.currentProjectId), { pins: metrics })))
            try {
                await save
            } catch {
                actions.pulsePinsSaved()
                toast.error({ title: "Couldn't save your numbers. Try again." })
                breakpoint()
                actions.loadPulsePins()
                actions.loadHighlights()
                return
            }
            actions.pulsePinsSaved()
            breakpoint()
            actions.loadHighlights()
        },
        togglePulsePin: ({ pin, source }) => {
            if (values.pulsePinsUnavailableReason) {
                return
            }
            const pinned = values.pulsePins.some((existing) => existing.key === pin.key)
            const pinnedCountBefore = values.pulsePins.length
            if (pulsePinLimitReason(pinnedCountBefore, pinned)) {
                return
            }
            actions.setPinnedPulseKeys(
                pinned
                    ? values.pulsePins.filter((existing) => existing.key !== pin.key)
                    : [...values.pulsePins, { key: pin.key, name: pin.name, dashboard_id: pin.dashboard_id ?? null }]
            )
            posthog.capture(pinned ? 'today pulse number unpinned' : 'today pulse number pinned', {
                kind: pulseKind(pin.key),
                source,
                pinned_count_before: pinnedCountBefore,
            })
        },
        pulseEditorOpened: () => {
            posthog.capture('today pulse editor opened', { kept_count: values.pulsePins.length })
        },
        loadPulsePinsSuccess: () => {
            cache.pinsLoadRetries = 0
            actions.setPulsePlaces(values.pulsePlacement.places)
        },
        setHiddenPulseMetrics: () => {
            actions.setPulsePlaces(values.pulsePlacement.places)
        },
        loadPulsePinsFailure: () => {
            if ((cache.pinsLoadRetries ?? 0) >= PINS_LOAD_RETRIES) {
                actions.pulsePinsLoadGaveUp()
                return
            }
            cache.pinsLoadRetries = (cache.pinsLoadRetries ?? 0) + 1
            cache.disposables.add(() => {
                const retry = window.setTimeout(() => actions.loadPulsePins(), PINS_LOAD_RETRY_MS)
                return () => clearTimeout(retry)
            }, 'pulsePinsLoadRetry')
        },
        hidePulseMetric: ({ metric, position }) => {
            actions.setHiddenPulseMetrics({
                ...values.hiddenPulseMetrics,
                [hiddenHighlightKey(values.currentProjectId, metric.key)]: true,
            })
            posthog.capture('today pulse metric hidden', {
                kind: pulseKind(metric.key),
                reason: metric.reason,
                position,
            })
            toast.success({
                title: 'Hidden from Today',
                action: { label: 'Undo', onClick: () => actions.unhidePulseMetric(metric, position) },
            })
        },
        unhidePulseMetric: ({ metric, position }) => {
            const { [hiddenHighlightKey(values.currentProjectId, metric.key)]: _, ...rest } = values.hiddenPulseMetrics
            actions.setHiddenPulseMetrics(rest)
            posthog.capture('today pulse metric unhidden', {
                kind: pulseKind(metric.key),
                reason: metric.reason,
                position,
            })
        },
        hideHighlight: ({ item, position }) => {
            const day = values.highlights?.day
            if (!day) {
                return
            }
            const kept = Object.fromEntries(
                Object.entries(values.hiddenHighlights).filter(([, hiddenOn]) => hiddenOn === day)
            )
            actions.setHiddenHighlights({ ...kept, [hiddenHighlightKey(values.currentProjectId, item.key)]: day })
            posthog.capture('today highlight hidden', {
                label: item.label,
                source: item.source,
                position,
                score: item.score,
            })
        },
        unhideHighlight: ({ item, position }) => {
            const { [hiddenHighlightKey(values.currentProjectId, item.key)]: _, ...rest } = values.hiddenHighlights
            actions.setHiddenHighlights(rest)
            posthog.capture('today highlight unhidden', {
                label: item.label,
                source: item.source,
                position,
                score: item.score,
            })
        },
        highlightOpened: ({ item, position }) => {
            posthog.capture('today highlight opened', {
                label: item.label,
                source: item.source,
                position,
                score: item.score,
            })
        },
        pulseMetricOpened: ({ metric, position }) => {
            posthog.capture('today pulse metric opened', {
                kind: pulseKind(metric.key),
                reason: metric.reason,
                position,
            })
        },
        pulseMetricPreviewed: ({ metric, position }) => {
            const previewed: Set<string> = (cache.previewedPulseMetrics ??= new Set<string>())
            if (previewed.has(metric.key)) {
                return
            }
            previewed.add(metric.key)
            posthog.capture('today pulse metric previewed', {
                kind: pulseKind(metric.key),
                reason: metric.reason,
                position,
            })
        },
        retryPulse: () => {
            if (!values.highlightsLoading && (values.highlightsFailed || values.highlights?.status !== 'computing')) {
                actions.loadHighlights(true)
            }
        },
        loadHighlightsSuccess: ({ highlights }) => {
            cache.highlightsUnavailable = highlights === null
            const load = cache.pulseLoad as PulseLoad | undefined
            if (load && !load.finished) {
                load.firstResponseAt ??= performance.now()
                load.loadingMode = highlights?.pulse_slots == null ? 'complete' : 'progressive'
                load.responseCount += 1
                load.initialStatus ??= highlights?.status ?? null
            }
            if (!highlights) {
                return
            }
            actions.setPulsePlaces(values.pulsePlacement.places)
            if (highlights.status === 'computing') {
                cache.disposables.add(() => {
                    const poll = window.setTimeout(() => actions.loadHighlights(), HIGHLIGHTS_POLL_MS)
                    return () => clearTimeout(poll)
                }, 'highlightsPoll')
                return
            }
            if (cache.highlightsLoadedCaptured) {
                return
            }
            cache.highlightsLoadedCaptured = true
            posthog.capture('today highlights loaded', {
                status: highlights.status,
                item_count: highlights.items.length,
                risk_count: highlights.items.filter((item) => item.label === 'risk').length,
                opportunity_count: highlights.items.filter((item) => item.label === 'opportunity').length,
                sources: highlights.items.map((item) => item.source),
                pulse_count: values.pulseTiles.length,
                pulse_candidate_count: highlights.pulse.length,
                pinned_count: highlights.pins.length,
                pulse_reasons: values.pulseTiles.map((metric) => metric.reason),
            })
        },
    })),
    afterMount(({ actions, cache }) => {
        actions.loadHighlights()
        actions.loadPulsePins()
        cache.disposables.add(() => {
            const timer = window.setTimeout(() => actions.stopWaitingForHighlights(), HIGHLIGHTS_WAIT_MS)
            return () => clearTimeout(timer)
        }, 'highlightsWait')
    }),
])
