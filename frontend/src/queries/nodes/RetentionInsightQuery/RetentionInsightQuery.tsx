import { RetentionQuery } from '~/queries/schema'
import { InsightLogicProps, FilterType, InsightType } from '~/types'
import { BindLogic } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { AdHocInsight } from 'lib/components/AdHocInsight/AdHocInsight'

const filtersFromTrendsQuery = (query: RetentionQuery): Partial<FilterType> => {
    return {
        insight: InsightType.RETENTION,
        ...query.dateRange,
        properties: query.properties,
        filter_test_accounts: query.filterTestAccounts,
        ...query.retentionFilter,
    }
}

/** Use new RetentionQuery and transform it into old insight props to display the retention graph. */
export function RetentionInsightQuery({ query }: { query: RetentionQuery }): JSX.Element {
    const filters: Partial<FilterType> = filtersFromTrendsQuery(query)
    const insightProps: InsightLogicProps = { dashboardItemId: 'new', cachedInsight: { filters } }

    return (
        <BindLogic logic={insightLogic} props={insightProps} key={JSON.stringify(filters)}>
            <AdHocInsight filters={filters} style={{ height: 500, border: '1px var(--primary) solid' }} />
        </BindLogic>
    )
}
