import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { PageHeader } from 'lib/components/PageHeader'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs/LemonTabs'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { EmbeddedAnalyticsFilters } from './EmbeddedAnalyticsFilters'
import { EmbeddedTiles } from './EmbeddedAnalyticsTiles'
import { EmbeddedTab } from './common'
import { embeddedAnalyticsLogic } from './embeddedAnalyticsLogic'
import { QueryEndpoints } from './query-endpoints/QueryEndpoints'

export function EmbeddedAnalyticsDashboard(): JSX.Element {
    return (
        <BindLogic logic={embeddedAnalyticsLogic} props={{}}>
            <SceneContent className="EmbeddedAnalyticsDashboard w-full flex flex-col">
                <EmbeddedAnalyticsTabs />

                <PageHeader
                    buttons={
                        <LemonButton
                            data-attr="new-query-endpoint"
                            onClick={() => {
                                // TODO: Once editor is refactored, allow sending #output-pane-tab=query-endpoint
                                router.actions.push(urls.sqlEditor())
                            }}
                            type="primary"
                            tooltip="This will redirect you to the SQL Editor."
                        >
                            New query endpoint
                        </LemonButton>
                    }
                />
                <MainContent />
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

const MainContent = (): JSX.Element => {
    const { activeTab } = useValues(embeddedAnalyticsLogic)
    const { tiles } = useValues(embeddedAnalyticsLogic)

    switch (activeTab) {
        case EmbeddedTab.QUERY_ENDPOINTS:
            return <QueryEndpoints />
        case EmbeddedTab.USAGE_ANALYTICS:
            return (
                <>
                    <EmbeddedAnalyticsFilters />
                    <EmbeddedTiles tiles={tiles} />
                </>
            )
    }
}
