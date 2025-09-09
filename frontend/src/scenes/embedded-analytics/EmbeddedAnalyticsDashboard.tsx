import { useValues } from 'kea'

import { Tiles } from 'scenes/web-analytics/WebAnalyticsDashboard'

import { embeddedAnalyticsLogic } from './embeddedAnalyticsLogic'

export function EmbeddedAnalyticsDashboard(): JSX.Element {
    const { tiles } = useValues(embeddedAnalyticsLogic)

    return <Tiles tiles={tiles} />
}
