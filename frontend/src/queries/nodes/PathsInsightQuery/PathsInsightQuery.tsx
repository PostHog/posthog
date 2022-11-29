import { PathsQuery } from '~/queries/schema'
import { InsightLogicProps, FilterType, InsightType } from '~/types'
import { BindLogic } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { AdHocInsight } from 'lib/components/AdHocInsight/AdHocInsight'

const filtersFromTrendsQuery = (query: PathsQuery): Partial<FilterType> => {
    return {
        insight: InsightType.PATHS,
        ...query.dateRange,
        properties: query.properties,
        filter_test_accounts: query.filterTestAccounts,
        ...query.pathsFilter,
    }
}

/** Use new PathsQuery and transform it into old insight props to display the funnels graph. */
export function PathsInsightQuery({ query }: { query: PathsQuery }): JSX.Element {
    const filters: Partial<FilterType> = filtersFromTrendsQuery(query)
    const insightProps: InsightLogicProps = { dashboardItemId: 'new', cachedInsight: { filters } }

    return (
        <BindLogic logic={insightLogic} props={insightProps} key={JSON.stringify(filters)}>
            <AdHocInsight filters={filters} style={{ height: 500, border: '1px var(--primary) solid' }} />
        </BindLogic>
    )
}
