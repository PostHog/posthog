import { BindLogic, useActions, useValues } from 'kea'

import { QueryCard } from 'lib/components/Cards/InsightCard/QueryCard'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { pageCollectionId } from '~/queries/nodes/DataNode/pageCollections'
import { ReloadAll } from '~/queries/nodes/DataNode/Reload'

import { featureFlagUsageLogic } from './featureFlagUsageLogic'
import { FLAG_EVALUATIONS_RETENTION_DAYS } from './featureFlagUsageQueries'

const FEATURE_FLAG_USAGE_DATA_COLLECTION_NODE_ID = pageCollectionId('feature-flag-usage')

export function FeatureFlagUsageMetrics({ id }: { id: number }): JSX.Element {
    const logic = featureFlagUsageLogic({ id })
    const { dateRange, dateOptions, readsFlagEvaluationsTable, usageCharts } = useValues(logic)
    const { setDates } = useActions(logic)

    return (
        <BindLogic logic={dataNodeCollectionLogic} props={{ key: FEATURE_FLAG_USAGE_DATA_COLLECTION_NODE_ID }}>
            <div className="flex flex-col gap-4" data-attr="feature-flag-usage-inline">
                <div className="flex flex-wrap items-center gap-2">
                    <DateFilter
                        dateFrom={dateRange.date_from ?? null}
                        dateTo={dateRange.date_to ?? null}
                        dateOptions={dateOptions}
                        onChange={(fromDate, toDate) => setDates(fromDate, toDate)}
                    />
                    <ReloadAll />
                    {readsFlagEvaluationsTable && (
                        <span className="text-secondary text-xs">
                            Flag evaluations are kept for {FLAG_EVALUATIONS_RETENTION_DAYS} days.
                        </span>
                    )}
                </div>
                <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
                    {usageCharts.map((chart) => (
                        <QueryCard
                            key={chart.key}
                            uniqueKey={`feature-flag-usage-${id}-${chart.key}`}
                            title={chart.title}
                            description={chart.description}
                            query={chart.query}
                            context={{
                                insightProps: {
                                    // The events and flag_evaluations versions of a chart share a chart key, so
                                    // the query kind keeps their insight and data node logics apart.
                                    dashboardItemId: `new-AdHoc.feature-flag-usage-${id}-${chart.query.kind}-${chart.key}`,
                                    dataNodeCollectionId: FEATURE_FLAG_USAGE_DATA_COLLECTION_NODE_ID,
                                    query: chart.query,
                                },
                                ...chart.emptyState,
                            }}
                        />
                    ))}
                </div>
            </div>
        </BindLogic>
    )
}
