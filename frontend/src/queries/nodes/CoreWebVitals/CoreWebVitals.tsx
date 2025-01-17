import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { Query } from '~/queries/Query/Query'
import { AnyResponseType, CoreWebVitalsQuery, CoreWebVitalsQueryResponse } from '~/queries/schema'
import { QueryContext } from '~/queries/types'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'
import { CoreWebVitalsContent } from './CoreWebVitalsContent'
import { CoreWebVitalsTab } from './CoreWebVitalsTab'
import { getMetric, LONG_METRIC_NAME } from './definitions'

let uniqueNode = 0
export function CoreWebVitals(props: {
    query: CoreWebVitalsQuery
    cachedResults?: AnyResponseType
    context: QueryContext
}): JSX.Element | null {
    const [key] = useState(() => `CoreWebVitals.${uniqueNode++}`)
    const logic = dataNodeLogic({
        query: props.query,
        key,
        cachedResults: props.cachedResults,
        loadPriority: 0,
        onData: () => {},
        dataNodeCollectionId: key,
    })

    const { coreWebVitalsPercentile, coreWebVitalsTab, coreWebVitalsMetricQuery } = useValues(webAnalyticsLogic)
    const { setCoreWebVitalsTab } = useActions(webAnalyticsLogic)
    const { response } = useValues(logic)
    const coreWebVitalsQueryResponse = response as CoreWebVitalsQueryResponse | undefined

    const INP = useMemo(
        () => getMetric(coreWebVitalsQueryResponse?.results, 'INP', coreWebVitalsPercentile),
        [coreWebVitalsQueryResponse, coreWebVitalsPercentile]
    )
    const LCP = useMemo(
        () => getMetric(coreWebVitalsQueryResponse?.results, 'LCP', coreWebVitalsPercentile),
        [coreWebVitalsQueryResponse, coreWebVitalsPercentile]
    )
    const CLS = useMemo(
        () => getMetric(coreWebVitalsQueryResponse?.results, 'CLS', coreWebVitalsPercentile),
        [coreWebVitalsQueryResponse, coreWebVitalsPercentile]
    )
    const FCP = useMemo(
        () => getMetric(coreWebVitalsQueryResponse?.results, 'FCP', coreWebVitalsPercentile),
        [coreWebVitalsQueryResponse, coreWebVitalsPercentile]
    )

    return (
        <div className="border rounded bg-bg-muted flex-1 flex flex-col">
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 cursor-pointer border-b divide-y sm:divide-y-2 xl:divide-y-0 divide-x-0 sm:divide-x xl:divide-x-2">
                <CoreWebVitalsTab
                    metric="INP"
                    label={LONG_METRIC_NAME.INP}
                    value={INP}
                    isActive={coreWebVitalsTab === 'INP'}
                    setTab={() => setCoreWebVitalsTab('INP')}
                    inSeconds
                />
                <CoreWebVitalsTab
                    metric="LCP"
                    label={LONG_METRIC_NAME.LCP}
                    value={LCP}
                    isActive={coreWebVitalsTab === 'LCP'}
                    setTab={() => setCoreWebVitalsTab('LCP')}
                    inSeconds
                />
                <CoreWebVitalsTab
                    metric="FCP"
                    label={LONG_METRIC_NAME.FCP}
                    value={FCP}
                    isActive={coreWebVitalsTab === 'FCP'}
                    setTab={() => setCoreWebVitalsTab('FCP')}
                    inSeconds
                />
                <CoreWebVitalsTab
                    metric="CLS"
                    label={LONG_METRIC_NAME.CLS}
                    value={CLS}
                    isActive={coreWebVitalsTab === 'CLS'}
                    setTab={() => setCoreWebVitalsTab('CLS')}
                />
            </div>

            <div className="flex flex-row gap-2 p-4">
                <CoreWebVitalsContent coreWebVitalsQueryResponse={coreWebVitalsQueryResponse} />
                <div className="flex-1">
                    <Query query={coreWebVitalsMetricQuery} readOnly embedded />
                </div>
            </div>
        </div>
    )
}
