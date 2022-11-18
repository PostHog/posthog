import { SavedInsightNode } from '~/queries/schema'
import { InsightLogicProps, ItemMode } from '~/types'
import { BindLogic } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightContainer } from 'scenes/insights/InsightContainer'

export function SavedInsightQuery({ query }: { query: SavedInsightNode }): JSX.Element {
    const insightProps: InsightLogicProps = { dashboardItemId: query.shortId }
    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <InsightContainer insightMode={ItemMode.View} disableHeader disableTable disableCorrelationTable />
        </BindLogic>
    )
}
