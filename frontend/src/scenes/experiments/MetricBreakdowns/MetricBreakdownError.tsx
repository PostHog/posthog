import { ExperimentMetric } from '~/queries/schema/schema-general'
import { BreakdownAttributionType } from '~/types'

import { MetricBreakdowns } from './MetricBreakdowns'

export type MetricBreakdownErrorProps = {
    metric: ExperimentMetric
    isAlternatingRow: boolean
    onRemoveBreakdown: (index: number) => void
    onAttributionChange: (attributionType: BreakdownAttributionType, attributionValue?: number) => void
    onBreakdownLimitChange: (breakdownLimit: number) => void
}

export function MetricBreakdownError({
    metric,
    isAlternatingRow,
    onRemoveBreakdown,
    onAttributionChange,
    onBreakdownLimitChange,
}: MetricBreakdownErrorProps): JSX.Element {
    return (
        <tr data-breakdown-row className="hover:bg-bg-hover group">
            <td colSpan={7} className={`p-0 border-t border-b ${isAlternatingRow ? 'bg-bg-table' : 'bg-bg-light'}`}>
                <div className="p-1">
                    <MetricBreakdowns
                        metric={metric}
                        onRemoveBreakdown={onRemoveBreakdown}
                        onAttributionChange={onAttributionChange}
                        onBreakdownLimitChange={onBreakdownLimitChange}
                    />
                </div>
            </td>
        </tr>
    )
}
