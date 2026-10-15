import posthog from 'posthog-js'

import { IconChevronDown, IconRewindPlay } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu'
import { type ExperimentRecordingModes } from 'scenes/experiments/ExperimentView/experimentRecordingModes'
import {
    type ExperimentRecordingsEntryPoint,
    type ExperimentReplayMetricFilterMode,
    experimentRecordingsUrl,
} from 'scenes/experiments/ExperimentView/experimentRecordingsDeepLink'

import { ExperimentMetric } from '~/queries/schema/schema-general'
import { Experiment } from '~/types'

/** Where the results table is rendered, so telemetry can tell the inline table from the modal. */
export type ExperimentResultsSurface = 'inline' | 'details_modal'

export interface VariantRecordingsButtonProps {
    experiment: Experiment
    metric: ExperimentMetric
    variantKey: string
    /** The baseline row answers a different question, so its clicks are counted separately. */
    isBaseline: boolean
    surface: ExperimentResultsSurface
    /** Resolved once for the whole table, since every row links to the same metric. */
    modes: ExperimentRecordingModes
}

/**
 * The recordings link on a variant row: one click opens the Recordings tab on the metric's default
 * population, and the caret offers the other populations plus every recording of the variant.
 *
 * When the tab cannot select the metric there is no default population, so the one click opens
 * every recording of the variant and carries the reason for the tab to explain.
 *
 * The tab scopes its list per person through the experiment's exposure, so no link here needs an
 * exposure filter of its own.
 */
export function VariantRecordingsButton({
    experiment,
    metric,
    variantKey,
    isBaseline,
    surface,
    modes,
}: VariantRecordingsButtonProps): JSX.Element {
    const { metricSelectable, unselectableReason, unselectableCode, defaultMode, menuItems } = modes
    // A metric the tab would drop must not reach the URL, or the list would answer without the
    // filter the label promised.
    const metricUuid = metricSelectable ? (metric.uuid ?? null) : null

    const linkTo = (
        metricFilterMode: ExperimentReplayMetricFilterMode | null,
        entry: ExperimentRecordingsEntryPoint
    ): string =>
        experimentRecordingsUrl(experiment.id, {
            variantKey,
            metricUuid: metricFilterMode === null ? null : metricUuid,
            metricFilterMode,
            entry,
            // Only the one-click fallback needs it. A menu item named "All recordings of this
            // variant" already says what it opens, so an explanation there would answer a question
            // the reader did not ask.
            metricUnavailable: entry === 'results_button' ? unselectableCode : null,
        })

    const trackClick = (
        metricFilterMode: ExperimentReplayMetricFilterMode | null,
        trigger: 'button' | 'menu'
    ): void => {
        // Pinned: a dashboard counts this event name.
        posthog.capture('viewed recordings from experiment', {
            variant: variantKey,
            metric_kind: metric.metric_type,
            metric_filter: metricFilterMode,
            trigger,
            surface,
            is_baseline: isBaseline,
            // Null on an ordinary click. Non-null means the metric filter was dropped and the link
            // opened the variant's whole list instead, which is the population this measures. The
            // menu reports null even for the same metric: its "all recordings" item is a choice the
            // viewer made, not a filter taken away, and the tab's own events count it the same way.
            metric_unavailable_reason: trigger === 'button' ? unselectableCode : null,
        })
    }

    return (
        <LemonButton
            size="xsmall"
            type="secondary"
            truncate
            icon={<IconRewindPlay />}
            tooltip={unselectableReason ?? 'Watch recordings of this variant on the Recordings tab.'}
            to={linkTo(defaultMode, 'results_button')}
            data-attr="experiment-metrics-view-recordings"
            onClick={() => trackClick(defaultMode, 'button')}
            sideAction={{
                icon: <IconChevronDown />,
                'data-attr': 'experiment-metrics-recordings-menu',
                tooltip: 'Pick which recordings to watch',
                dropdown: {
                    placement: 'bottom-end',
                    onVisibilityChange: (visible) => {
                        if (visible) {
                            posthog.capture('experiment recordings menu opened', {
                                variant: variantKey,
                                metric_kind: metric.metric_type,
                                surface,
                            })
                        }
                    },
                    overlay: (
                        <LemonMenuOverlay
                            items={[
                                {
                                    title: `Watch recordings of ${variantKey}`,
                                    items: [
                                        ...menuItems.map((item) => ({
                                            label: item.label,
                                            tooltip: item.tooltip,
                                            disabledReason: item.disabledReason ?? undefined,
                                            to: linkTo(item.mode, 'results_menu'),
                                            'data-attr': `experiment-metrics-recordings-menu-${item.mode}`,
                                            onClick: () => trackClick(item.mode, 'menu'),
                                        })),
                                        {
                                            label: 'All recordings of this variant',
                                            tooltip: 'Watch every recording of this variant, with no metric filter.',
                                            to: linkTo(null, 'results_menu'),
                                            'data-attr': 'experiment-metrics-recordings-menu-all',
                                            onClick: () => trackClick(null, 'menu'),
                                        },
                                    ],
                                },
                            ]}
                        />
                    ),
                },
            }}
        >
            View recordings
        </LemonButton>
    )
}
