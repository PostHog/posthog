import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import {
    ExperimentMetric,
    isExperimentMeanMetric,
    isExperimentRatioMetric,
    NewExperimentQueryResponse,
} from '~/queries/schema/schema-general'
import { VariantTag } from '~/scenes/experiments/ExperimentView/VariantTag'
import {
    ExperimentVariantResult,
    formatChanceToWinForGoal,
    formatDeltaPercent,
    formatMetricValue,
    isBayesianResult,
    isCupedAdjusted,
} from '~/scenes/experiments/MetricsView/shared/utils'

import { CUPED_ADJUSTED_EXPLANATION, CupedAdjustedTag } from 'products/experiments/frontend/components/CupedAdjustedTag'

type NotebookCompactTableProps = {
    result: NewExperimentQueryResponse
    metric: ExperimentMetric
}

type TableRow = ExperimentVariantResult & { key: string; isBaseline: boolean }

export function NotebookCompactTable({ result, metric }: NotebookCompactTableProps): JSX.Element {
    const goal = 'goal' in metric ? metric.goal : undefined

    const columns: LemonTableColumns<TableRow> = [
        {
            key: 'variant',
            title: 'Variant',
            render: (_, item) => <VariantTag variantKey={item.key} />,
        },
        {
            key: 'value',
            title: isExperimentMeanMetric(metric) ? 'Mean' : isExperimentRatioMetric(metric) ? 'Ratio' : 'Conversion',
            render: (_, item) => {
                const value = formatMetricValue(item, metric)
                const delta = item.isBaseline ? null : formatDeltaPercent(item)

                return (
                    <div className="flex flex-col">
                        <span className="font-semibold">{value}</span>
                        {delta && (
                            <span className="flex items-center gap-1">
                                <span
                                    className={`text-xs ${
                                        delta.startsWith('+')
                                            ? 'text-success'
                                            : delta.startsWith('-')
                                              ? 'text-danger'
                                              : ''
                                    }`}
                                >
                                    {delta}
                                </span>
                                {isCupedAdjusted(item) && (
                                    <Tooltip title={CUPED_ADJUSTED_EXPLANATION}>
                                        {/* Tooltip attaches its handlers to this element, because CupedAdjustedTag forwards no props. */}
                                        <span className="flex">
                                            <CupedAdjustedTag />
                                        </span>
                                    </Tooltip>
                                )}
                            </span>
                        )}
                        {item.isBaseline && <span className="text-xs text-muted">Baseline</span>}
                    </div>
                )
            },
        },
        {
            key: 'win_probability',
            title: 'Win prob.',
            render: (_, item) => {
                if (item.isBaseline) {
                    return <span className="text-muted">—</span>
                }
                if (!isBayesianResult(item)) {
                    return <span className="text-muted">—</span>
                }
                return <span className="font-semibold">{formatChanceToWinForGoal(item, goal)}</span>
            },
        },
    ]

    const dataSource: TableRow[] = [
        ...(result.baseline ? [{ ...result.baseline, isBaseline: true } as TableRow] : []),
        ...(result.variant_results?.map((v) => ({ ...v, isBaseline: false }) as TableRow) || []),
    ]

    return <LemonTable columns={columns} dataSource={dataSource} size="small" />
}
