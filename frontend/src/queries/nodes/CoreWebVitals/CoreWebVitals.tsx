import { LemonSkeleton } from '@posthog/lemon-ui'
import { clsx } from 'clsx'
import { useValues } from 'kea'
import { useMemo, useState } from 'react'
import { CoreWebVitalsPercentile, webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import {
    AnyResponseType,
    CoreWebVitals,
    CoreWebVitalsItem,
    CoreWebVitalsQuery,
    CoreWebVitalsQueryResponse,
} from '~/queries/schema'
import { QueryContext } from '~/queries/types'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'

const getMetric = (
    results: CoreWebVitalsItem[] | undefined,
    metric: CoreWebVitals,
    percentile: CoreWebVitalsPercentile
): number | undefined => {
    return results
        ?.filter((result) => result.action.custom_name === metric)
        .find((result) => result.action.math === percentile)
        ?.data.slice(-1)[0]
}

let uniqueNode = 0
export function CoreWebVitals(props: {
    query: CoreWebVitalsQuery
    cachedResults?: AnyResponseType
    context: QueryContext
}): JSX.Element | null {
    const [tab, setTab] = useState<CoreWebVitals>('INP')
    const [key] = useState(() => `CoreWebVitals.${uniqueNode++}`)
    const logic = dataNodeLogic({
        query: props.query,
        key,
        cachedResults: props.cachedResults,
        loadPriority: 0,
        onData: () => {},
        dataNodeCollectionId: key,
    })

    const { coreWebVitalsPercentile } = useValues(webAnalyticsLogic)
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
        <div className="border rounded bg-bg-light flex-1 flex flex-col">
            <div className="flex flex-row flex-wrap justify-between items-center [&>*:not(:last-child)]:border-r cursor-pointer">
                <CoreWebVitalsTab
                    value={INP}
                    label="Interaction to Next Paint"
                    isActive={tab === 'INP'}
                    setTab={() => setTab('INP')}
                />
                <CoreWebVitalsTab
                    value={LCP}
                    label="Largest Contentful Paint"
                    isActive={tab === 'LCP'}
                    setTab={() => setTab('LCP')}
                />
                <CoreWebVitalsTab
                    value={CLS}
                    label="Cumulative Layout Shift"
                    isActive={tab === 'CLS'}
                    setTab={() => setTab('CLS')}
                />
                <CoreWebVitalsTab
                    value={FCP}
                    label="First Contentful Paint"
                    isActive={tab === 'FCP'}
                    setTab={() => setTab('FCP')}
                />
            </div>

            {tab === 'INP' && <div>INP</div>}
            {tab === 'LCP' && <div>LCP</div>}
            {tab === 'CLS' && <div>CLS</div>}
            {tab === 'FCP' && <div>FCP</div>}
        </div>
    )
}

function CoreWebVitalsTab({
    value,
    label,
    isActive,
    setTab,
}: {
    value: number | undefined
    label: string
    isActive: boolean
    setTab: () => void
}): JSX.Element {
    // Use a dash to represent lack of value
    const parsedValue = value === undefined ? undefined : value === 0 ? '-' : (value / 1000).toFixed(2)

    return (
        <div
            onClick={setTab}
            className={clsx('flex flex-1 flex-col items-center justify-start border-b p-2', {
                'font-bold border-b-2 border-b-primary': isActive,
            })}
        >
            <span className="text-sm">{label}</span>
            <div className="flex flex-row items-center">
                <span>{parsedValue || <LemonSkeleton fade className="w-4 h-4" />}</span>
                <span className="text-sm">s</span>
            </div>
            <span>Progress bar comes here</span>
        </div>
    )
}
