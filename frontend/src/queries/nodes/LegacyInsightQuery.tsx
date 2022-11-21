import { LegacyQuery } from '~/queries/schema'
import { InsightLogicProps } from '~/types'
import { BindLogic } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { AdHocInsight } from 'lib/components/AdHocInsight/AdHocInsight'

/** Given a FilterType, display a graph. */
export function LegacyInsightQuery({ query }: { query: LegacyQuery }): JSX.Element {
    const insightProps: InsightLogicProps = { dashboardItemId: 'new', cachedInsight: { filters: query.filters } }
    return (
        <BindLogic logic={insightLogic} props={insightProps} key={JSON.stringify(query.filters)}>
            <AdHocInsight filters={query.filters} style={{ height: 300, border: '1px var(--primary) solid' }} />
        </BindLogic>
    )
}
