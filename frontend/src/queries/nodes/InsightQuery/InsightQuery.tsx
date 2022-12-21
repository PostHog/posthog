import { InsightQueryNode } from '~/queries/schema'
import { InsightLogicProps, FilterType } from '~/types'
import { BindLogic } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { AdHocInsight } from 'lib/components/AdHocInsight/AdHocInsight'

import { queryNodeToFilter } from './utils/queryNodeToFilter'

/** Use new insight queries and transform them into old insight props to display the respective visualization. */
export function InsightQuery({ query }: { query: InsightQueryNode }): JSX.Element {
    const filters: Partial<FilterType> = queryNodeToFilter(query)
    const insightProps: InsightLogicProps = { dashboardItemId: 'new', cachedInsight: { filters } }

    return (
        <BindLogic logic={insightLogic} props={insightProps} key={JSON.stringify(filters)}>
            <AdHocInsight filters={filters} style={{ height: 500, border: '1px var(--primary) solid' }} />
        </BindLogic>
    )
}
