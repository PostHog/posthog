import { BreakdownFilter } from '~/queries/schema/schema-general'
import { TrendResult } from '~/types'

// The exporter writes one row per series, with a column per date bucket. These names must stay in
// step with the trends branch of _convert_response_to_csv_data in
// products/exports/backend/tasks/csv_exporter.py — a name that drifts exports as an empty column.
export function trendsExportColumns(results: TrendResult[], breakdownFilter?: BreakdownFilter | null): string[] {
    if (results.length === 0) {
        return []
    }

    const columns: string[] = []
    const seen = new Set<string>()
    const add = (name: string): void => {
        if (name && !seen.has(name)) {
            seen.add(name)
            columns.push(name)
        }
    }

    const breakdowns = breakdownFilter?.breakdowns?.length
        ? breakdownFilter.breakdowns
        : breakdownFilter?.breakdown
          ? [{ property: breakdownFilter.breakdown }]
          : []

    add('series')

    // When comparing periods, the previous series is indexed with an offset, so its own labels are
    // the wrong ones.
    const currentLabels = results.find((result) => result.compare_label === 'current')?.labels

    for (const result of results) {
        if (result.action?.custom_name) {
            add('custom name')
        }

        if (result.breakdown_value !== undefined) {
            const breakdownValues = Array.isArray(result.breakdown_value)
                ? result.breakdown_value
                : [result.breakdown_value]
            breakdownValues.forEach((_, index) => {
                const property = breakdowns[index]?.property
                if (property) {
                    add(Array.isArray(property) ? property.join(', ') : String(property))
                }
            })
        }

        if (result.aggregated_value != null) {
            add('Total Sum')
        } else if (result.data?.length) {
            const labels = currentLabels ?? result.labels ?? []
            result.data.forEach((_, index) => {
                if (index < labels.length) {
                    add(labels[index])
                }
            })
        }
    }

    return columns
}
