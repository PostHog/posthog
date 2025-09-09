import { useValues } from 'kea'

import { EmbeddedTiles } from './EmbeddedAnalyticsTiles'
import { embeddedAnalyticsLogic } from './embeddedAnalyticsLogic'

export function EmbeddedAnalyticsDashboard(): JSX.Element {
    const { tiles } = useValues(embeddedAnalyticsLogic)

    return <EmbeddedTiles tiles={tiles} />
}
