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
    const { metricSelectable, unselectableReason, defaultMode, menuItems } = modes
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
        })
    }

    return (
        <LemonButton
            size="xsmall"
            type="secondary"
            truncate
            icon={<IconRewindPlay />}
            tooltip="Watch recordings of this variant on the Recordings tab."
            // Without a default mode the one click would open the variant's whole list under a
            // label that promises the metric's population. The caret still offers that list, named.
            disabledReason={defaultMode === null ? unselectableReason : null}
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
