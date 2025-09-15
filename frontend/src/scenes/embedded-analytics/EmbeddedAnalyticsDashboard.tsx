import { BindLogic, useActions, useValues } from 'kea'

import { LemonTabs } from 'lib/lemon-ui/LemonTabs/LemonTabs'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { EmbeddedAnalyticsFilters } from './EmbeddedAnalyticsFilters'
import { EmbeddedTiles } from './EmbeddedAnalyticsTiles'
import { EmbeddedTab } from './common'
import { embeddedAnalyticsLogic } from './embeddedAnalyticsLogic'

export function EmbeddedAnalyticsDashboard(): JSX.Element {
    const { tiles } = useValues(embeddedAnalyticsLogic)

    return (
        <BindLogic logic={embeddedAnalyticsLogic} props={{}}>
            <SceneContent className="EmbeddedAnalyticsDashboard w-full flex flex-col">
                <EmbeddedAnalyticsTabs />
                {/* <Filters tabs={<></>} /> */}

                <EmbeddedAnalyticsFilters />
                <EmbeddedTiles tiles={tiles} />
            </SceneContent>
        </BindLogic>
    )
}

const EmbeddedAnalyticsTabs = (): JSX.Element => {
    const { activeTab } = useValues(embeddedAnalyticsLogic)
    const { setActiveTab } = useActions(embeddedAnalyticsLogic)

    return (
        <LemonTabs<EmbeddedTab>
            activeKey={activeTab}
            onChange={setActiveTab}
            tabs={[
                { key: EmbeddedTab.QUERY_ENDPOINTS, label: 'Query Endpoints' },
                { key: EmbeddedTab.USAGE_ANALYTICS, label: 'API Usage' },
            ]}
        />
    )
}
