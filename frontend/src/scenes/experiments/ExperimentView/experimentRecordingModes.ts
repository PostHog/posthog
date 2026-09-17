import { ExperimentMetric, isExperimentFunnelMetric } from '~/queries/schema/schema-general'

import {
    getFunnelDropoffReason,
    getMetricSessionFilters,
    getMetricSourceEventNames,
    getMetricUnlinkableReason,
} from '../utils'
import type { ExperimentReplayMetricFilterMode } from './experimentRecordingsDeepLink'

export const METRIC_WITHOUT_UUID_REASON = "This metric can't be selected on the Recordings tab."

/**
 * The modes a results row offers. A row's link carries a single metric, and over one metric
 * "fired any" asks the same question as "fired all", so only the tab's own control offers it.
 */
type ExperimentRecordingMenuMode = Exclude<ExperimentReplayMetricFilterMode, 'fired_any'>

interface ExperimentRecordingModeLabel {
    label: string
    tooltip: string
}

/**
 * What each mode is called on the two surfaces that offer it. The Recordings tab picks a mode and a
 * metric separately, so its control names the mode alone. A results row carries one metric, so its
 * menu item can name what that metric counts. Both phrasings sit together, so a copy change lands
 * in one place.
 */
type ExperimentRecordingModeCopy<M extends ExperimentReplayMetricFilterMode> = {
    control: ExperimentRecordingModeLabel
} & (M extends ExperimentRecordingMenuMode
    ? { menu: (eventNames: string[]) => ExperimentRecordingModeLabel }
    : { menu?: undefined })

/**
 * A metric that counts several events resolves `fired_all` as the `fired_any` bucket, so a session
 * matches on any one of them. The copy says "or" for that reason.
 */
const MODE_COPY: { [M in ExperimentReplayMetricFilterMode]: ExperimentRecordingModeCopy<M> } = {
    fired_all: {
        control: {
            label: 'Fired all',
            tooltip: 'Sessions that fired events for every selected metric.',
        },
        menu: (eventNames) => {
            const events = eventNames.join(' or ')
            return {
                label: events ? `Fired ${events}` : 'Fired metric events',
                tooltip: events
                    ? `Watch sessions of this variant that fired ${events}.`
                    : "Watch sessions of this variant that fired the metric's events.",
            }
        },
    },
    fired_any: {
        control: {
            label: 'Fired any',
            tooltip: 'Sessions that fired events for at least one of the selected metrics.',
        },
    },
    no_metric_activity: {
        control: {
            label: 'Fired none',
            tooltip: 'Sessions that fired no events for any of the selected metrics.',
        },
        menu: (eventNames) => {
            const events = eventNames.join(' or ')
            return {
                label: events ? `Didn't fire ${events}` : "Didn't fire metric events",
                tooltip: events
                    ? `Watch sessions of this variant that never fired ${events}. The same person may have fired one in another session.`
                    : "Watch sessions of this variant that fired none of the metric's events. The same person may have fired them in another session.",
            }
        },
    },
    funnel_completed: {
        control: {
            label: 'Finished funnel',
            tooltip:
                "Sessions that saw the experiment and fired a funnel metric's last step during the recording. The same person may have finished it in a different session.",
        },
        menu: () => ({
            label: 'Finished funnel',
            tooltip:
                "Watch sessions of this variant that fired the funnel's last step. The same person may have finished the funnel in another session.",
        }),
    },
    funnel_dropoff: {
        control: {
            label: "Didn't finish funnel",
            tooltip:
                "Sessions that saw the experiment but didn't fire a funnel metric's last step during the recording. The exposure counts as the funnel's first step. The same person may have finished it in a later session.",
        },
        menu: () => ({
            label: "Didn't finish funnel",
            tooltip:
                "Watch sessions of this variant that didn't fire the funnel's last step. The same person may have finished the funnel in another session.",
        }),
    },
}

/**
 * The Recordings tab's mode control. Listed from the widest population to the narrowest, which is
 * not the order the parse list uses.
 */
const MODE_CONTROL_ORDER: ExperimentReplayMetricFilterMode[] = [
    'fired_all',
    'fired_any',
    'no_metric_activity',
    'funnel_completed',
    'funnel_dropoff',
]

export const EXPERIMENT_RECORDING_MODE_OPTIONS: {
    value: ExperimentReplayMetricFilterMode
    label: string
    tooltip: string
}[] = MODE_CONTROL_ORDER.map((value) => ({ value, ...MODE_COPY[value].control }))

/**
 * The distinct events a label may name. An action matches several events and names none of them,
 * and a data-warehouse source has no session event at all, so a metric that counts either keeps the
 * generic label rather than naming a source the recordings filter doesn't match on.
 */
function labelEventNames(metric: ExperimentMetric): string[] {
    const filters = getMetricSessionFilters(metric)
    if (filters.length === 0 || !filters.every((filter) => 'type' in filter && filter.type === 'events')) {
        return []
    }
    return getMetricSourceEventNames(metric)
}

/** One mode a results row offers for its metric, resolved to what the menu item renders. */
export interface ExperimentRecordingModeItem {
    mode: ExperimentRecordingMenuMode
    label: string
    tooltip: string
    /** Why the mode can't be applied to this metric, or null when it can. */
    disabledReason: string | null
}

export interface ExperimentRecordingModes {
    /** False when the Recordings tab would drop this metric, so a link to it must carry no metric. */
    metricSelectable: boolean
    unselectableReason: string | null
    /** The mode a one-click link applies. Null when the metric can't be selected. */
    defaultMode: ExperimentReplayMetricFilterMode | null
    /**
     * The two modes that read this metric. "All recordings of this variant" is not here: it carries
     * no metric, and its label names the variant, which this module doesn't know.
     */
    menuItems: [ExperimentRecordingModeItem, ExperimentRecordingModeItem]
}

/**
 * Which recordings a results row can open for one metric, and what to call each of them.
 *
 * Every eligibility rule comes from the helpers the Recordings tab itself uses, so a row can only
 * offer what the tab would accept.
 *
 * Pass an empty `unlinkableEventNames` while the linkability check loads. Both reasons fail open on
 * it, so nothing is disabled until the check says otherwise.
 */
export function getMetricRecordingModes(
    metric: ExperimentMetric,
    unlinkableEventNames: Set<string>
): ExperimentRecordingModes {
    // The tab selects a metric by uuid and skips the ones without it, so a link to a uuid-less
    // metric would land on a list the metric filter never reaches.
    const unselectableReason =
        (metric.uuid ? null : METRIC_WITHOUT_UUID_REASON) ?? getMetricUnlinkableReason(metric, unlinkableEventNames)
    const funnel = isExperimentFunnelMetric(metric)
    // Both funnel modes read the last step, so a step no recording can be matched on disables the
    // pair rather than one half of it.
    const funnelReason = funnel ? getFunnelDropoffReason(metric, unlinkableEventNames) : null
    const modes: [ExperimentRecordingMenuMode, ExperimentRecordingMenuMode] = funnel
        ? ['funnel_completed', 'funnel_dropoff']
        : ['fired_all', 'no_metric_activity']
    const eventNames = funnel ? [] : labelEventNames(metric)
    const disabledReason = unselectableReason ?? funnelReason

    let defaultMode: ExperimentReplayMetricFilterMode | null = null
    if (!unselectableReason) {
        // A funnel whose last step can't be matched still narrows on its earlier steps, so the
        // one-click link falls back to the mode that reads them.
        defaultMode = funnelReason ? 'fired_all' : modes[0]
    }

    return {
        metricSelectable: unselectableReason === null,
        unselectableReason,
        defaultMode,
        menuItems: [
            { mode: modes[0], ...MODE_COPY[modes[0]].menu(eventNames), disabledReason },
            { mode: modes[1], ...MODE_COPY[modes[1]].menu(eventNames), disabledReason },
        ],
    }
}
