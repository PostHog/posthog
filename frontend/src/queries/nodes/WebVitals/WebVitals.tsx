import { BuiltLogic, LogicWrapper, useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { Link } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider/LemonSlider'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { ProductIntentContext, addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { urls } from 'scenes/urls'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { Query } from '~/queries/Query/Query'
import { AnyResponseType, WebVitalsQuery, WebVitalsQueryResponse } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { ProductKey } from '~/types'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'
import { WebVitalsContent } from './WebVitalsContent'
import { WebVitalsTab } from './WebVitalsTab'
import { getMetric } from './definitions'

let uniqueNode = 0
export function WebVitals(props: {
    query: WebVitalsQuery
    cachedResults?: AnyResponseType
    context: QueryContext
    attachTo?: LogicWrapper | BuiltLogic
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

    useAttachedLogic(logic, props.attachTo)

    const { webVitalsPercentile, webVitalsTab, webVitalsMetricQuery, webVitalsSamplingRate } =
        useValues(webAnalyticsLogic)
    const { setWebVitalsTab, setWebVitalsSamplingRate } = useActions(webAnalyticsLogic)
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
        <div className="flex flex-col flex-1 gap-4">
            <div className="flex flex-col gap-1">
                <div className="grid gap-2 grid-cols-1 sm:grid-cols-2 xl:grid-cols-4">
                    <WebVitalsTab
                        metric="INP"
                        value={INP}
                        isActive={webVitalsTab === 'INP'}
                        setTab={() => setWebVitalsTab('INP')}
                        isLoading={responseLoading}
                    />
                    <WebVitalsTab
                        metric="LCP"
                        value={LCP}
                        isActive={webVitalsTab === 'LCP'}
                        setTab={() => setWebVitalsTab('LCP')}
                        isLoading={responseLoading}
                    />
                    <WebVitalsTab
                        metric="FCP"
                        value={FCP}
                        isActive={webVitalsTab === 'FCP'}
                        setTab={() => setWebVitalsTab('FCP')}
                        isLoading={responseLoading}
                    />
                    <WebVitalsTab
                        metric="CLS"
                        value={CLS}
                        isActive={webVitalsTab === 'CLS'}
                        setTab={() => setWebVitalsTab('CLS')}
                        isLoading={responseLoading}
                    />
                </div>
                <div className="flex flex-col sm:flex-row gap-2 items-start sm:items-center justify-between">
                    <span className="text-xs text-text-tertiary">
                        Metrics above are from the last day in the selected time range.{' '}
                        <Link
                            to="https://posthog.com/docs/web-analytics/web-vitals#web-vitals-dashboard"
                            target="_blank"
                        >
                            Learn more in the Docs.
                        </Link>
                    </span>
                    <div className="flex items-center gap-2">
                        <span className="text-xs text-text-tertiary whitespace-nowrap">Sampling:</span>
                        <div className="flex items-center gap-2 w-48">
                            <span className="text-xs text-text-tertiary">
                                {webVitalsSamplingRate ? `${webVitalsSamplingRate}%` : 'Auto'}
                            </span>
                            <LemonSlider
                                min={1}
                                max={100}
                                step={1}
                                value={webVitalsSamplingRate ?? 100}
                                onChange={(value) => setWebVitalsSamplingRate(value === 100 ? null : value)}
                            />
                        </div>
                    </div>
                </div>
            </div>

            <div className="flex flex-col sm:flex-row gap-2">
                <WebVitalsContent webVitalsQueryResponse={webVitalsQueryResponse} isLoading={responseLoading} />
                <div className="flex flex-col flex-1 bg-surface-primary rounded border p-4">
                    <Query
                        query={webVitalsMetricQuery}
                        readOnly
                        embedded
                        context={{ renderEmptyStateAsSkeleton: true }}
                    />

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
