import { useActions, useValues } from 'kea'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { addProductIntentForCrossSell, ProductIntentContext } from 'lib/utils/product-intents'
import { useMemo, useState } from 'react'
import { urls } from 'scenes/urls'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { Query } from '~/queries/Query/Query'
import { AnyResponseType, WebVitalsQuery, WebVitalsQueryResponse } from '~/queries/schema'
import { QueryContext } from '~/queries/types'
import { ProductKey } from '~/types'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'
import { getMetric } from './definitions'
import { WebVitalsContent } from './WebVitalsContent'
import { WebVitalsTab } from './WebVitalsTab'

let uniqueNode = 0
export function WebVitals(props: {
    query: WebVitalsQuery
    cachedResults?: AnyResponseType
    context: QueryContext
}): JSX.Element | null {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [key] = useState(() => `WebVitals.${uniqueNode++}`)

    const logic = dataNodeLogic({
        query: props.query,
        key,
        cachedResults: props.cachedResults,
        loadPriority,
        onData,
        dataNodeCollectionId: dataNodeCollectionId ?? key,
    })

    const { webVitalsPercentile, webVitalsTab, webVitalsMetricQuery } = useValues(webAnalyticsLogic)
    const { setWebVitalsTab } = useActions(webAnalyticsLogic)
    const { response, responseLoading } = useValues(logic)

    // Manually handle loading state when loading to avoid showing stale data while refreshing
    const webVitalsQueryResponse = responseLoading ? undefined : (response as WebVitalsQueryResponse | undefined)

    const INP = useMemo(
        () => getMetric(webVitalsQueryResponse?.results, 'INP', webVitalsPercentile),
        [webVitalsQueryResponse, webVitalsPercentile]
    )
    const LCP = useMemo(
        () => getMetric(webVitalsQueryResponse?.results, 'LCP', webVitalsPercentile),
        [webVitalsQueryResponse, webVitalsPercentile]
    )
    const CLS = useMemo(
        () => getMetric(webVitalsQueryResponse?.results, 'CLS', webVitalsPercentile),
        [webVitalsQueryResponse, webVitalsPercentile]
    )
    const FCP = useMemo(
        () => getMetric(webVitalsQueryResponse?.results, 'FCP', webVitalsPercentile),
        [webVitalsQueryResponse, webVitalsPercentile]
    )

    return (
        <div className="border rounded bg-surface-tertiary flex-1 flex flex-col">
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 cursor-pointer border-b divide-y sm:divide-y-2 xl:divide-y-0 divide-x-0 sm:divide-x xl:divide-x-2">
                <WebVitalsTab
                    metric="INP"
                    value={INP}
                    isActive={webVitalsTab === 'INP'}
                    setTab={() => setWebVitalsTab('INP')}
                />
                <WebVitalsTab
                    metric="LCP"
                    value={LCP}
                    isActive={webVitalsTab === 'LCP'}
                    setTab={() => setWebVitalsTab('LCP')}
                />
                <WebVitalsTab
                    metric="FCP"
                    value={FCP}
                    isActive={webVitalsTab === 'FCP'}
                    setTab={() => setWebVitalsTab('FCP')}
                />
                <WebVitalsTab
                    metric="CLS"
                    value={CLS}
                    isActive={webVitalsTab === 'CLS'}
                    setTab={() => setWebVitalsTab('CLS')}
                />
            </div>

            <div className="flex flex-col sm:flex-row gap-2 p-4">
                <WebVitalsContent webVitalsQueryResponse={webVitalsQueryResponse} />
                <div className="flex flex-col flex-1">
                    <Query query={webVitalsMetricQuery} readOnly embedded />

                    <div className="flex w-full justify-end">
                        <LemonButton
                            to={urls.insightNew({ query: webVitalsMetricQuery })}
                            icon={<IconOpenInNew />}
                            size="small"
                            type="secondary"
                            onClick={() => {
                                void addProductIntentForCrossSell({
                                    from: ProductKey.WEB_ANALYTICS,
                                    to: ProductKey.PRODUCT_ANALYTICS,
                                    intent_context: ProductIntentContext.WEB_VITALS_INSIGHT,
                                })
                            }}
                        >
                            Open as new Insight
                        </LemonButton>
                    </div>
                </div>
            </div>
        </div>
    )
}
