import { ExperimentMetric, isExperimentFunnelMetric } from '~/queries/schema/schema-general'

import type { ExperimentReplayMetricFilterMode } from '../../ExperimentView/experimentRecordingsDeepLink'
import { getFunnelDropoffReason, getMetricSessionFilters } from '../../utils'
import { getMetricUnlinkableReason } from '../../viewRecordingsLinkabilityLogic'

const METRIC_WITHOUT_UUID_REASON = "This metric can't be selected on the Recordings tab."

/**
 * The event a session has to fire for the metric to count it, when the metric names one. An action
 * matches several events and names none of them, and a data-warehouse source has no session event
 * at all, so both fall back to the generic label.
 */
function primaryEventName(metric: ExperimentMetric): string | null {
    const [filter] = getMetricSessionFilters(metric)
    return filter && 'type' in filter && filter.type === 'events' && typeof filter.name === 'string' && filter.name
        ? filter.name
        : null
}

/** One of the two recordings links a results row offers, resolved to what the button renders. */
export interface ResultRowRecordingLink {
    label: string
    tooltip: string
    metricFilterMode: ExperimentReplayMetricFilterMode
    /** Frozen: autocapture dashboards and Playwright find the buttons by it. */
    dataAttr: string
    /** Why the link can't be followed, or null when it can. */
    disabledReason: string | null
}

/**
 * The pair of links a results row shows: sessions of this variant that reached the metric, and
 * sessions that did not. Both open the recordings tab, which scopes its list per person through the
 * experiment's exposure, so neither link needs an exposure event filter of its own.
 *
 * Pass an empty `unlinkableEventNames` while the linkability check loads. Both reasons fail open on
 * it, so the links stay enabled until the check says otherwise.
 */
export function getResultRowRecordingLinks(
    metric: ExperimentMetric,
    unlinkableEventNames: Set<string>
): [ResultRowRecordingLink, ResultRowRecordingLink] {
    const funnel = isExperimentFunnelMetric(metric)
    // The label names the event rather than the metric, because a metric's name is free text
    // ("Rageclicks per user") and rarely says what a session has to have fired.
    const eventName = funnel ? null : primaryEventName(metric)
    const links: [ResultRowRecordingLink, ResultRowRecordingLink] = funnel
        ? [
              {
                  label: 'Finished funnel',
                  tooltip:
                      "Watch sessions of this variant that fired the funnel's last step. The same person may have finished the funnel in another session.",
                  metricFilterMode: 'funnel_completed',
                  dataAttr: 'experiment-metrics-recordings-positive',
                  disabledReason: null,
              },
              {
                  label: "Didn't finish funnel",
                  tooltip:
                      "Watch sessions of this variant that didn't fire the funnel's last step. The same person may have finished the funnel in another session.",
                  metricFilterMode: 'funnel_dropoff',
                  dataAttr: 'experiment-metrics-recordings-negative',
                  disabledReason: null,
              },
          ]
        : [
              {
                  label: eventName ? `Fired ${eventName}` : 'Fired metric events',
                  tooltip: eventName
                      ? `Watch sessions of this variant that fired ${eventName}.`
                      : "Watch sessions of this variant that fired the metric's events.",
                  metricFilterMode: 'fired_all',
                  dataAttr: 'experiment-metrics-recordings-positive',
                  disabledReason: null,
              },
              {
                  label: eventName ? `Didn't fire ${eventName}` : "Didn't fire metric events",
                  tooltip: eventName
                      ? `Watch sessions of this variant that fired no ${eventName} event. The same person may have fired it in another session.`
                      : "Watch sessions of this variant that fired none of the metric's events. The same person may have fired them in another session.",
                  metricFilterMode: 'no_metric_activity',
                  dataAttr: 'experiment-metrics-recordings-negative',
                  disabledReason: null,
              },
          ]

    // The tab selects a metric by uuid and skips the ones without it, so a link to a uuid-less
    // metric would land on a list the metric filter never reaches.
    const reason =
        (metric.uuid ? null : METRIC_WITHOUT_UUID_REASON) ??
        getMetricUnlinkableReason(metric, unlinkableEventNames) ??
        // Both funnel modes read the last step, so a step no recording can be matched on disables
        // the pair rather than one half of it.
        (funnel ? getFunnelDropoffReason(metric, unlinkableEventNames) : null)
    return reason
        ? [
              { ...links[0], disabledReason: reason },
              { ...links[1], disabledReason: reason },
          ]
        : links
}
