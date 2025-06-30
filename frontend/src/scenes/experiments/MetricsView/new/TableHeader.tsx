import { type ExperimentVariantResult, isBayesianResult } from '../shared/utils'
import { NewExperimentQueryResponse } from '~/queries/schema/schema-general'

interface TableHeaderProps {
    results: NewExperimentQueryResponse[]
}

export function TableHeader({ results }: TableHeaderProps): JSX.Element {
    // Determine if we should show "P-value" or "Chance to Win" based on the first available result
    const firstVariantResult = results
        .flatMap((result) => result?.variant_results || [])
        .find((variant): variant is ExperimentVariantResult => Boolean(variant))

    const isBayesian = firstVariantResult ? isBayesianResult(firstVariantResult) : false
    const significanceHeader = isBayesian ? 'Chance to Win' : 'P-value'

    return (
        <thead>
            <tr>
                <th className="w-1/5 border-b-2 border-r border-border bg-bg-table p-3 text-left text-xs font-semibold text-text-secondary sticky top-0 z-10">
                    Metric
                </th>
                <th className="w-24 border-b-2 border-r border-border bg-bg-table p-3 text-left text-xs font-semibold text-text-secondary sticky top-0 z-10">
                    Baseline
                </th>
                <th className="w-20 border-b-2 border-r border-border bg-bg-table p-3 text-left text-xs font-semibold text-text-secondary sticky top-0 z-10">
                    Variant
                </th>
                <th className="w-24 border-b-2 border-r border-border bg-bg-table p-3 text-left text-xs font-semibold text-text-secondary sticky top-0 z-10">
                    Value
                </th>
                <th className="w-20 border-b-2 border-r border-border bg-bg-table p-3 text-left text-xs font-semibold text-text-secondary sticky top-0 z-10">
                    {significanceHeader}
                </th>
                <th className="min-w-[400px] border-b-2 border-border bg-bg-table p-3 text-center text-xs font-semibold text-text-secondary sticky top-0 z-10">
                    Chart
                </th>
            </tr>
        </thead>
    )
}
