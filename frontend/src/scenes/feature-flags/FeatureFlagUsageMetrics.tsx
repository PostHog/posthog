import { useActions, useValues } from 'kea'

import { QueryCard } from 'lib/components/Cards/InsightCard/QueryCard'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import { featureFlagUsageLogic } from './featureFlagUsageLogic'

export function FeatureFlagUsageMetrics({ id }: { id: number }): JSX.Element {
    const logic = featureFlagUsageLogic({ id })
    const { dateRange, usageCharts } = useValues(logic)
    const { setDates } = useActions(logic)

    return (
        <div className="flex flex-col gap-4" data-attr="feature-flag-usage-inline">
            <div>
                <DateFilter
                    dateFrom={dateRange.date_from ?? null}
                    dateTo={dateRange.date_to ?? null}
                    onChange={(fromDate, toDate) => setDates(fromDate, toDate)}
                />
            </div>
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                {usageCharts.map((chart) => (
                    <QueryCard
                        key={chart.key}
                        uniqueKey={`feature-flag-usage-${id}-${chart.key}`}
                        title={chart.title}
                        description={chart.description}
                        query={chart.query}
                    />
                ))}
            </div>
        </div>
    )
}
