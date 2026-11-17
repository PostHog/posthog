import { useValues } from 'kea'
import posthog from 'posthog-js'

import { IconCopy, IconExternal } from '@posthog/icons'

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

export interface VariantRecordingsLink {
    key: string
    label: string
    tooltip?: string
    disabledReason?: string
    url: string
    dataAttr: string
    onClick: () => void
}

export interface VariantSqlAction {
    key: string
    label: string
    icon: JSX.Element
    disabledReason?: string
    newTabUrl?: string
    dataAttr: string
    onClick: () => void
}

export interface VariantActions {
    trackMenuOpened: () => void
    recordings: VariantRecordingsLink[]
    sqlActions: VariantSqlAction[]
}

export function useVariantActions({
    experiment,
    metric,
    variantKey,
    isBaseline,
    modes,
    hogql,
    clickhouseSql,
}: VariantActionsMenuProps): VariantActions {
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

    const recordings: VariantRecordingsLink[] = [
        ...modes.menuItems.map((item) => ({
            key: item.mode,
            label: item.label,
            tooltip: item.tooltip,
            disabledReason: item.disabledReason ?? undefined,
            url: recordingsLink(item.mode),
            dataAttr: `experiment-variant-menu-recordings-${item.mode}`,
            onClick: () => trackRecordingsClick(item.mode),
        })),
        {
            key: 'all',
            label: 'All recordings of this variant',
            tooltip: 'Watch every recording of this variant, with no metric filter.',
            url: recordingsLink(null),
            dataAttr: 'experiment-variant-menu-recordings-all',
            onClick: () => trackRecordingsClick(null),
        },
    ]

    const sqlActions: VariantSqlAction[] = [
        {
            key: 'copy-sql',
            label: 'Copy SQL',
            icon: <IconCopy />,
            disabledReason: noSqlReason,
            dataAttr: 'experiment-variant-menu-copy-sql',
            onClick: () => {
                if (hogql) {
                    void copyToClipboard(hogql, 'SQL')
                    posthog.capture('experiment metric sql copied', sqlProperties)
                }
            },
        },
        {
            key: 'open-sql',
            label: 'Open in SQL editor',
            icon: <IconExternal />,
            disabledReason: noSqlReason,
            newTabUrl: hogql ? urls.sqlEditor({ query: hogql }) : undefined,
            dataAttr: 'experiment-variant-menu-open-sql',
            onClick: () => posthog.capture('experiment metric sql opened in editor', sqlProperties),
        },
    ]

    if (featureFlags[FEATURE_FLAGS.EXPERIMENTS_SHOW_SQL]) {
        sqlActions.push({
            key: 'copy-clickhouse-sql',
            label: 'Copy ClickHouse SQL',
            icon: <IconCopy />,
            disabledReason: clickhouseSql ? undefined : 'This metric has no ClickHouse SQL yet',
            dataAttr: 'experiment-variant-menu-copy-clickhouse-sql',
            onClick: () => {
                if (clickhouseSql) {
                    void copyToClipboard(clickhouseSql, 'ClickHouse SQL')
                }
            },
        })
    }

    return {
        trackMenuOpened: () =>
            posthog.capture('experiment recordings menu opened', {
                variant: variantKey,
                metric_kind: metric.metric_type,
                surface: 'metrics_table',
            }),
        recordings,
        sqlActions,
    }
}
