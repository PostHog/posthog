import { BindLogic, useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { BigLeaguesHog } from 'lib/components/hedgehogs'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs/LemonTabs'
import { OutputTab } from 'scenes/data-warehouse/editor/outputPaneLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { ProductKey } from '~/types'

import { EmbeddedAnalyticsFilters } from './EmbeddedAnalyticsFilters'
import { EmbeddedTiles } from './EmbeddedAnalyticsTiles'
import { EmbeddedTab } from './common'
import { embeddedAnalyticsLogic } from './embeddedAnalyticsLogic'
import { QueryEndpoints } from './query-endpoints/QueryEndpoints'
import { queryEndpointsLogic } from './query-endpoints/queryEndpointsLogic'

const EMBEDDED_ANALYTICS_QUERY_ENDPOINTS_PRODUCT_DESCRIPTION =
    'Embedded analytics help you create pre-built SQL queries that you can easily use in your application via our API. Please note that embedded analytics is in alpha and may not be fully reliable or set in stone.'
const EMBEDDED_ANALYTICS_API_USAGE_PRODUCT_DESCRIPTION =
    'Monitor your API usage and cost. Please note that embedded analytics is in alpha and may not be fully reliable or set in stone.'

export function EmbeddedAnalyticsContent({ tabId }: { tabId: string }): JSX.Element {
    const { isEmpty } = useValues(queryEndpointsLogic({ tabId }))
    const { activeTab } = useValues(embeddedAnalyticsLogic({ tabId }))
    return (
        <BindLogic logic={embeddedAnalyticsLogic} props={{ tabId: tabId }}>
            <BindLogic logic={queryEndpointsLogic} props={{ tabId: tabId }}>
                <SceneContent className="EmbeddedAnalyticsContent w-full flex flex-col">
                    <EmbeddedAnalyticsTabs />
                    <ProductIntroduction
                        className="m-0"
                        productName="embedded analytics"
                        productKey={ProductKey.EMBEDDED_ANALYTICS}
                        thingName="query endpoint"
                        description={
                            activeTab === EmbeddedTab.QUERY_ENDPOINTS
                                ? EMBEDDED_ANALYTICS_QUERY_ENDPOINTS_PRODUCT_DESCRIPTION
                                : EMBEDDED_ANALYTICS_API_USAGE_PRODUCT_DESCRIPTION
                        }
                        docsURL="https://posthog.com/docs/embedded-analytics"
                        customHog={BigLeaguesHog}
                        isEmpty={isEmpty}
                        action={() =>
                            router.actions.push(
                                urls.sqlEditor(undefined, undefined, undefined, undefined, OutputTab.QueryEndpoint)
                            )
                        }
                    />

                    <MainContent tabId={tabId} />
                </SceneContent>
            </BindLogic>
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
            sceneInset
            tabs={[
                {
                    key: EmbeddedTab.QUERY_ENDPOINTS,
                    label: 'Query endpoints',
                    link: urls.embeddedAnalytics(EmbeddedTab.QUERY_ENDPOINTS),
                },
                { key: EmbeddedTab.USAGE, label: 'API usage', link: urls.embeddedAnalytics(EmbeddedTab.USAGE) },
            ]}
        />
    )
}

const MainContent = ({ tabId }: { tabId: string }): JSX.Element => {
    const { activeTab } = useValues(embeddedAnalyticsLogic)
    const { tiles } = useValues(embeddedAnalyticsLogic)

    switch (activeTab) {
        case EmbeddedTab.QUERY_ENDPOINTS:
            return <QueryEndpoints tabId={tabId} />
        case EmbeddedTab.USAGE:
            return (
                <>
                    <EmbeddedAnalyticsFilters />
                    <EmbeddedTiles tiles={tiles} />
                </>
            )
    }
}
