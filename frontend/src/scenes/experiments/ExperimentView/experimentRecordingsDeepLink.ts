import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import type { ExperimentIdType } from '~/types'

/**
 * How the selected metrics narrow the list.
 *
 * `fired_all` and `funnel_completed` compose event filters client-side and are uncapped. The other
 * three are server computed: the recordings query carries one operator for its whole filter tree,
 * so an OR, an absence, and a drop-off can only come back as an explicit session-id list, which the
 * endpoint bounds. Those modes show a capped, most-recent-first slice.
 */
export const EXPERIMENT_REPLAY_METRIC_FILTER_MODES = [
    'fired_all',
    'fired_any',
    'no_metric_activity',
    'funnel_dropoff',
    'funnel_completed',
] as const

export type ExperimentReplayMetricFilterMode = (typeof EXPERIMENT_REPLAY_METRIC_FILTER_MODES)[number]

/**
 * Whether the mode reads a funnel metric's last step, so it only accepts a funnel whose last step
 * can be matched to recordings. Both funnel modes share that eligibility rule.
 */
export function isFunnelMode(mode: ExperimentReplayMetricFilterMode): boolean {
    return mode === 'funnel_dropoff' || mode === 'funnel_completed'
}

/**
 * The search params that preselect the recordings tab, so a results row can open the population it
 * names instead of the replay page's own list. The tab consumes them on mount and removes them from
 * the URL, after which its persisted state is the source of truth. `metric` is taken by the
 * create flow's prefill, so the metric param here is `metric_uuid`.
 */
export const EXPERIMENT_RECORDINGS_DEEP_LINK_PARAMS = ['variant', 'metric_uuid', 'metric_filter'] as const

export interface ExperimentRecordingsDeepLink {
    /** A variant key of the experiment's flag. Null selects every variant. */
    variantKey: string | null
    /** One metric uuid. Null leaves the metric filter menu unselected. */
    metricUuid: string | null
    /** Null falls back to the tab's default mode. */
    metricFilterMode: ExperimentReplayMetricFilterMode | null
}

/** The recordings tab's key in the experiment scene's tab bar. */
const RECORDINGS_TAB = 'recordings'

export function experimentRecordingsUrl(experimentId: ExperimentIdType, link: ExperimentRecordingsDeepLink): string {
    return combineUrl(urls.experiment(experimentId), {
        tab: RECORDINGS_TAB,
        ...(link.variantKey !== null ? { variant: link.variantKey } : {}),
        ...(link.metricUuid !== null ? { metric_uuid: link.metricUuid } : {}),
        ...(link.metricFilterMode !== null ? { metric_filter: link.metricFilterMode } : {}),
    }).url
}

/**
 * Null when the URL carries none of the three keys, which is the ordinary case and must not move
 * the tab's persisted state. A value the experiment does not own is left to the tab's own
 * selectors, which drop an unknown variant key or metric uuid, so a stale link degrades to the
 * tab's defaults. An unknown mode is dropped here instead, against the closed list above.
 */
export function parseExperimentRecordingsDeepLink(
    searchParams: Record<string, any>
): ExperimentRecordingsDeepLink | null {
    if (!EXPERIMENT_RECORDINGS_DEEP_LINK_PARAMS.some((param) => searchParams[param] !== undefined)) {
        return null
    }
    return {
        variantKey: typeof searchParams.variant === 'string' ? searchParams.variant : null,
        metricUuid: typeof searchParams.metric_uuid === 'string' ? searchParams.metric_uuid : null,
        metricFilterMode:
            EXPERIMENT_REPLAY_METRIC_FILTER_MODES.find((mode) => mode === searchParams.metric_filter) ?? null,
    }
}
