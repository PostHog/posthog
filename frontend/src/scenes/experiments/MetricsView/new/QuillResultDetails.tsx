import { useValues } from 'kea'

import { DataTable, Text } from '@posthog/quill'
import type { DataTableProps } from '@posthog/quill'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { ExperimentFunnelChart } from 'scenes/experiments/charts/funnel/ExperimentFunnelChart'
import { teamLogic } from 'scenes/teamLogic'

import {
    ExperimentMetric,
    NewExperimentQueryResponse,
    isExperimentFunnelMetric,
    isExperimentQuantileMetric,
} from '~/queries/schema/schema-general'
import { Experiment } from '~/types'

import { QuillHelpTooltip } from '../../ExperimentView/QuillCardParts'
import { QuillVariantTag } from '../../ExperimentView/QuillVariantTag'
import {
    ExperimentVariantResult,
    formatChanceToWinForGoal,
    formatIntervalPercent,
    formatMetricValue,
    formatPValue,
    isBayesianResult,
    isFrequentistResult,
} from '../shared/utils'
import {
    RESULT_EVENTS_HELP,
    RESULT_EXPOSURES_HELP,
    RESULT_INTERVAL_HELP,
    resultExperimentQuery,
    resultIntervalLabel,
    resultValueLabel,
    statisticalMeasureLabel,
} from './ResultDetails'

type ResultRow = ExperimentVariantResult & { key: string }
type ResultDataTable = DataTableProps<ResultRow, unknown>

function HeaderWithHelp({ label, help }: { label: string; help: string }): JSX.Element {
    return (
        <span className="inline-flex items-center gap-1">
            {label}
            <QuillHelpTooltip label={label} help={help} />
        </span>
    )
}

function Muted(): JSX.Element {
    return <span className="text-muted-foreground">—</span>
}

export function QuillResultDetails({
    experiment,
    result,
    metric,
}: {
    experiment: Experiment
    result: NewExperimentQueryResponse
    metric: ExperimentMetric
}): JSX.Element {
    const { baseCurrency } = useValues(teamLogic)
    const baselineKey = result.baseline?.key

    const columns: ResultDataTable['columns'] = [
        {
            id: 'variant',
            header: 'Variant',
            enableSorting: false,
            cell: ({ row: { original } }) => <QuillVariantTag variantKey={original.key} />,
        },
        {
            id: 'total-users',
            header: () => <HeaderWithHelp label="Exposures" help={RESULT_EXPOSURES_HELP} />,
            enableSorting: false,
            cell: ({ row: { original } }) => humanFriendlyNumber(original.number_of_samples),
        },
        ...(isExperimentQuantileMetric(metric)
            ? [
                  {
                      id: 'events',
                      header: () => <HeaderWithHelp label="Events" help={RESULT_EVENTS_HELP} />,
                      enableSorting: false,
                      cell: ({ row: { original } }: { row: { original: ResultRow } }) =>
                          humanFriendlyNumber(original.denominator_sum ?? 0),
                  },
              ]
            : []),
        {
            id: 'value',
            header: resultValueLabel(metric),
            enableSorting: false,
            cell: ({ row: { original } }) => formatMetricValue(original, metric, baseCurrency),
        },
        {
            id: 'statistical_measure',
            header: statisticalMeasureLabel(result),
            enableSorting: false,
            cell: ({ row: { original } }) => {
                if (original.key === baselineKey) {
                    return <Muted />
                }
                if (isBayesianResult(original)) {
                    return (
                        <Text size="xs" weight="semibold" render={<span />}>
                            {formatChanceToWinForGoal(original, metric.goal)}
                        </Text>
                    )
                }
                if (isFrequentistResult(original)) {
                    return (
                        <Text size="xs" weight="semibold" render={<span />}>
                            {formatPValue(original.p_value)}
                        </Text>
                    )
                }
                return <Muted />
            },
        },
        {
            id: 'significant',
            header: 'Significant',
            enableSorting: false,
            cell: ({ row: { original } }) => {
                if (original.key === baselineKey || !('significant' in original)) {
                    return <Muted />
                }
                return original.significant ? <span className="font-semibold text-success-foreground">Yes</span> : 'No'
            },
        },
        {
            id: 'interval',
            header: () => <HeaderWithHelp label={resultIntervalLabel(result)} help={RESULT_INTERVAL_HELP} />,
            enableSorting: false,
            cell: ({ row: { original } }) =>
                original.key === baselineKey ? <Muted /> : formatIntervalPercent(original),
        },
    ]

    const rows: ResultRow[] = [
        ...(result.baseline ? [result.baseline as ResultRow] : []),
        ...((result.variant_results || []) as ResultRow[]),
    ]

    return (
        <div className="flex flex-col divide-y divide-border">
            <DataTable columns={columns} data={rows} fullWidth size="sm" getRowId={(row) => row.key} />
            {isExperimentFunnelMetric(metric) && (
                <ExperimentFunnelChart
                    result={result}
                    experiment={experiment}
                    metric={metric}
                    experimentQuery={resultExperimentQuery(experiment, metric)}
                    embedded
                />
            )}
        </div>
    )
}
