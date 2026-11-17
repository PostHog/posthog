import { useValues } from 'kea'
import posthog from 'posthog-js'

import { IconCopy, IconEllipsis, IconExternal, IconRewindPlay } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { type ExperimentRecordingModes } from 'scenes/experiments/ExperimentView/experimentRecordingModes'
import {
    type ExperimentReplayMetricFilterMode,
    experimentRecordingsUrl,
} from 'scenes/experiments/ExperimentView/experimentRecordingsDeepLink'
import { urls } from 'scenes/urls'

import { ExperimentMetric } from '~/queries/schema/schema-general'
import { Experiment } from '~/types'

export interface VariantActionsMenuProps {
    experiment: Experiment
    metric: ExperimentMetric
    variantKey: string
    isBaseline: boolean
    modes: ExperimentRecordingModes
    hogql?: string
    clickhouseSql?: string
}

export function VariantActionsMenu({
    experiment,
    metric,
    variantKey,
    isBaseline,
    modes,
    hogql,
    clickhouseSql,
}: VariantActionsMenuProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const metricUuid = modes.metricSelectable ? (metric.uuid ?? null) : null

    const recordingsLink = (metricFilterMode: ExperimentReplayMetricFilterMode | null): string =>
        experimentRecordingsUrl(experiment.id, {
            variantKey,
            metricUuid: metricFilterMode === null ? null : metricUuid,
            metricFilterMode,
            entry: 'results_menu',
            metricUnavailable: null,
        })

    const trackRecordingsClick = (metricFilterMode: ExperimentReplayMetricFilterMode | null): void => {
        // Pinned: a dashboard counts this event name.
        posthog.capture('viewed recordings from experiment', {
            variant: variantKey,
            metric_kind: metric.metric_type,
            metric_filter: metricFilterMode,
            trigger: 'menu',
            surface: 'metrics_table',
            is_baseline: isBaseline,
            metric_unavailable_reason: null,
        })
    }

    const sqlProperties = { metric_kind: metric.metric_type, variant: variantKey, is_baseline: isBaseline }
    const noSqlReason = hogql ? undefined : 'This metric has no SQL yet'

    return (
        <LemonMenu
            placement="bottom-start"
            onVisibilityChange={(visible) => {
                if (visible) {
                    posthog.capture('experiment recordings menu opened', {
                        variant: variantKey,
                        metric_kind: metric.metric_type,
                        surface: 'metrics_table',
                    })
                }
            }}
            items={[
                {
                    items: [
                        {
                            label: 'View recordings',
                            icon: <IconRewindPlay />,
                            'data-attr': 'experiment-variant-menu-recordings',
                            placement: 'right-start',
                            items: [
                                ...modes.menuItems.map((item) => ({
                                    label: item.label,
                                    tooltip: item.tooltip,
                                    disabledReason: item.disabledReason ?? undefined,
                                    to: recordingsLink(item.mode),
                                    'data-attr': `experiment-variant-menu-recordings-${item.mode}`,
                                    onClick: () => trackRecordingsClick(item.mode),
                                })),
                                {
                                    label: 'All recordings of this variant',
                                    tooltip: 'Watch every recording of this variant, with no metric filter.',
                                    to: recordingsLink(null),
                                    'data-attr': 'experiment-variant-menu-recordings-all',
                                    onClick: () => trackRecordingsClick(null),
                                },
                            ],
                        },
                    ],
                },
                {
                    items: [
                        {
                            label: 'Copy SQL',
                            icon: <IconCopy />,
                            disabledReason: noSqlReason,
                            'data-attr': 'experiment-variant-menu-copy-sql',
                            onClick: () => {
                                if (hogql) {
                                    void copyToClipboard(hogql, 'SQL')
                                    posthog.capture('experiment metric sql copied', sqlProperties)
                                }
                            },
                        },
                        {
                            label: 'Open in SQL editor',
                            icon: <IconExternal />,
                            disabledReason: noSqlReason,
                            to: hogql ? urls.sqlEditor({ query: hogql }) : undefined,
                            targetBlank: true,
                            'data-attr': 'experiment-variant-menu-open-sql',
                            onClick: () => posthog.capture('experiment metric sql opened in editor', sqlProperties),
                        },
                        featureFlags[FEATURE_FLAGS.EXPERIMENTS_SHOW_SQL]
                            ? {
                                  label: 'Copy ClickHouse SQL',
                                  icon: <IconCopy />,
                                  disabledReason: clickhouseSql ? undefined : 'This metric has no ClickHouse SQL yet',
                                  'data-attr': 'experiment-variant-menu-copy-clickhouse-sql',
                                  onClick: () => {
                                      if (clickhouseSql) {
                                          void copyToClipboard(clickhouseSql, 'ClickHouse SQL')
                                      }
                                  },
                              }
                            : null,
                    ],
                },
            ]}
        >
            <LemonButton
                type="tertiary"
                size="xsmall"
                icon={<IconEllipsis />}
                tooltip="Variant actions"
                aria-label={`Actions for ${variantKey}`}
                data-attr="experiment-variant-actions"
            />
        </LemonMenu>
    )
}
