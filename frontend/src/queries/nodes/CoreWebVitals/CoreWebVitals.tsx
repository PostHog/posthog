import './CoreWebVitals.scss'

import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import { clsx } from 'clsx'
import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'
import { CoreWebVitalsPercentile, webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { Query } from '~/queries/Query/Query'
import {
    AnyResponseType,
    CoreWebVitalsItem,
    CoreWebVitalsMetric,
    CoreWebVitalsQuery,
    CoreWebVitalsQueryResponse,
} from '~/queries/schema'
import { QueryContext } from '~/queries/types'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'

type Threshold = { good: number; poor: number; end: number }
const THRESHOLDS: Record<CoreWebVitalsMetric, Threshold> = {
    INP: { good: 200, poor: 500, end: 550 },
    LCP: { good: 2500, poor: 4000, end: 4400 },
    CLS: { good: 0.1, poor: 0.25, end: 0.3 },
    FCP: { good: 1800, poor: 3000, end: 3300 },
}

const getMetric = (
    results: CoreWebVitalsItem[] | undefined,
    metric: CoreWebVitalsMetric,
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
                    label="Interaction to Next Paint"
                    value={INP}
                    isActive={coreWebVitalsTab === 'INP'}
                    setTab={() => setCoreWebVitalsTab('INP')}
                    inSeconds
                />
                <CoreWebVitalsTab
                    metric="LCP"
                    label="Largest Contentful Paint"
                    value={LCP}
                    isActive={coreWebVitalsTab === 'LCP'}
                    setTab={() => setCoreWebVitalsTab('LCP')}
                    inSeconds
                />
                <CoreWebVitalsTab
                    metric="FCP"
                    label="First Contentful Paint"
                    value={FCP}
                    isActive={coreWebVitalsTab === 'FCP'}
                    setTab={() => setCoreWebVitalsTab('FCP')}
                    inSeconds
                />
                <CoreWebVitalsTab
                    metric="CLS"
                    label="Cumulative Layout Shift"
                    value={CLS}
                    isActive={coreWebVitalsTab === 'CLS'}
                    setTab={() => setCoreWebVitalsTab('CLS')}
                />
            </div>

            <div>
                Actual content
                <Query query={coreWebVitalsMetricQuery} readOnly embedded />
            </div>

            {coreWebVitalsTab === 'INP' && <div>INP</div>}
            {coreWebVitalsTab === 'LCP' && <div>LCP</div>}
            {coreWebVitalsTab === 'CLS' && <div>CLS</div>}
            {coreWebVitalsTab === 'FCP' && <div>FCP</div>}
        </div>
    )
}

type ValueWithUnit = { value: string | undefined; unit: 's' | 'ms' | undefined }
const getValueWithUnit = (value: number | undefined, inSeconds: boolean): ValueWithUnit => {
    if (value === undefined) {
        return { value: undefined, unit: undefined }
    }

    // Use a dash to represent lack of value, it's unlikely that a metric will be 0
    if (value === 0) {
        return { value: '-', unit: undefined }
    }

    if (inSeconds) {
        return value < 1000 ? { value: value.toFixed(0), unit: 'ms' } : { value: (value / 1000).toFixed(2), unit: 's' }
    }

    return { value: value.toFixed(2), unit: undefined }
}

type Color = 'muted' | 'success' | 'warning' | 'danger'
const getThresholdColor = (value: number | undefined, threshold: Threshold): Color => {
    if (value === undefined) {
        return 'muted'
    }

    if (value <= threshold.good) {
        return 'success'
    }

    if (value <= threshold.poor) {
        return 'warning'
    }

    return 'danger'
}

function CoreWebVitalsTab({
    value,
    label,
    metric,
    isActive,
    setTab,
    inSeconds = false,
}: {
    value: number | undefined
    label: string
    metric: CoreWebVitalsMetric
    isActive: boolean
    setTab: () => void
    inSeconds?: boolean
}): JSX.Element {
    // TODO: Go back to using an actual value
    // Will keep this as is while we test what the UI looks like
    // const {value: parsedValue, unit } = getValueWithUnit(value, inSeconds)
    const newValue = true ? (inSeconds ? Math.random() * 10000 : Math.random()) : value
    const { value: parsedValue, unit } = getValueWithUnit(newValue, inSeconds)

    const threshold = THRESHOLDS[metric]
    const thresholdColor = getThresholdColor(newValue, threshold)

    return (
        <div
            onClick={setTab}
            className="CoreWebVitals__CoreWebVitalsTab flex flex-1 flex-row sm:flex-col justify-around sm:justify-start items-center sm:items-start p-4"
            data-active={isActive ? 'true' : 'false'}
        >
            <span className="text-sm hidden sm:block">{label}</span>
            <span className="text-sm block sm:hidden">
                <Tooltip title={label}>{metric}</Tooltip>
            </span>

            <div className="flex flex-row items-end">
                <span className={clsx('text-2xl', `text-${thresholdColor}`)}>
                    {parsedValue || <LemonSkeleton fade className="w-4 h-4" />}
                </span>
                {inSeconds && <span className="text-xs ml-1 mb-1">{unit}</span>}
            </div>

            <div className="w-full mt-2 hidden sm:block">
                {newValue && <ProgressBar value={newValue} threshold={threshold} />}
            </div>
        </div>
    )
}

interface ProgressBarProps {
    value: number
    threshold: Threshold
}

export function ProgressBar({ value, threshold }: ProgressBarProps): JSX.Element {
    const indicatorPercentage = Math.min((value / threshold.end) * 100, 100)

    const thresholdColor = getThresholdColor(value, threshold)
    const isGood = value <= threshold.good
    const isAverage = !isGood && value <= threshold.poor
    const isPoor = !isGood && !isAverage

    const goodWidth = (threshold.good / threshold.end) * 100
    const averageWidth = ((threshold.poor - threshold.good) / threshold.end) * 100
    const poorWidth = 100 - goodWidth - averageWidth

    return (
        <div className="w-full h-1 rounded-full relative">
            {/* Green segment up to "good" threshold */}
            <div
                className={clsx('absolute h-full rounded-full', { 'bg-success': isGood, 'bg-muted': !isGood })}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width: `${goodWidth}%` }}
            />

            {/* Yellow segment up to "poor" threshold */}
            <div
                className={clsx('absolute h-full rounded-full', { 'bg-warning': isAverage, 'bg-muted': !isAverage })}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ left: `${goodWidth + 1}%`, width: `${averageWidth - 1}%` }}
            />

            {/* Red segment after "poor" threshold */}
            <div
                className={clsx('absolute h-full rounded-full', { 'bg-danger': isPoor, 'bg-muted': !isPoor })}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ left: `${goodWidth + averageWidth + 1}%`, width: `${poorWidth - 1}%` }}
            />

            {/* Indicator line */}
            <div
                className={clsx('absolute w-0.5 h-3 -top-1', `bg-${thresholdColor}`)}
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    left: `${indicatorPercentage}%`,
                    transform: 'translateX(-50%)',
                }}
            />
        </div>
    )
}
