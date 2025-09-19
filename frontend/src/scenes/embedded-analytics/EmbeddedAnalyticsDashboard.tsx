import { BindLogic, useValues } from 'kea'

import { EmbeddedAnalyticsFilters } from './EmbeddedAnalyticsFilters'
import { EmbeddedTiles } from './EmbeddedAnalyticsTiles'
import { embeddedAnalyticsLogic } from './embeddedAnalyticsLogic'

export function EmbeddedAnalyticsDashboard(): JSX.Element {
    const { tiles } = useValues(embeddedAnalyticsLogic)

    return (
        <BindLogic logic={embeddedAnalyticsLogic} props={{}}>
            <EmbeddedAnalyticsFilters />
            <EmbeddedTiles tiles={tiles} />
        </BindLogic>
    )
}
