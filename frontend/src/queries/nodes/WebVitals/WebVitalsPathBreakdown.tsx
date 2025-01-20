import clsx from 'clsx'
import { useValues } from 'kea'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { useMemo, useState } from 'react'
import { WEB_VITALS_COLORS, WEB_VITALS_THRESHOLDS, webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import {
    AnyResponseType,
    WebVitalsMetricBand,
    WebVitalsPathBreakdownQuery,
    WebVitalsPathBreakdownQueryResponse,
} from '~/queries/schema'
import { QueryContext } from '~/queries/types'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'
import { getValueWithUnit, ICON_PER_BAND } from './definitions'

let uniqueNode = 0
export function WebVitalsPathBreakdown(props: {
    query: WebVitalsPathBreakdownQuery
    cachedResults?: AnyResponseType
    context: QueryContext
}): JSX.Element | null {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [key] = useState(() => `WebVitalsPathBreakdown.${uniqueNode++}`)

    const logic = dataNodeLogic({
        query: props.query,
        key,
        cachedResults: props.cachedResults,
        loadPriority,
        onData,
        dataNodeCollectionId: dataNodeCollectionId ?? key,
    })

    const { response, responseLoading } = useValues(logic)

    // Properly type it before passing to Content
    const webVitalsQueryResponse = response as WebVitalsPathBreakdownQueryResponse | undefined

    return (
        <div className="border rounded bg-bg-muted flex-1 flex flex-col min-h-60 h-full">
            <div className="grid grid-cols-1 md:grid-cols-3 divide-y md:divide-y-0 md:divide-x h-full">
                <div className="p-4">
                    <Header band="good" label="Good" />
                    <Content band="good" response={webVitalsQueryResponse} responseLoading={responseLoading} />
                </div>
                <div className="p-4">
                    <Header band="needs_improvements" label="Needs Improvements" />
                    <Content
                        band="needs_improvements"
                        response={webVitalsQueryResponse}
                        responseLoading={responseLoading}
                    />
                </div>
                <div className="p-4">
                    <Header band="poor" label="Poor" />
                    <Content band="poor" response={webVitalsQueryResponse} responseLoading={responseLoading} />
                </div>
            </div>
        </div>
    )
}

const Header = ({ band, label }: { band: WebVitalsMetricBand; label: string }): JSX.Element => {
    const { webVitalsTab } = useValues(webAnalyticsLogic)

    const Icon = ICON_PER_BAND[band]

    const thresholdText = useMemo(() => {
        const threshold = WEB_VITALS_THRESHOLDS[webVitalsTab]
        const inSeconds = webVitalsTab !== 'CLS'

        const { value: poorValue, unit: poorUnit } = getValueWithUnit(threshold.poor, inSeconds)
        const { value: goodValue, unit: goodUnit } = getValueWithUnit(threshold.good, inSeconds)

        if (band === 'poor') {
            return (
                <>
                    &gt; {poorValue}
                    {poorUnit}
                </>
            )
        }

        if (band === 'needs_improvements') {
            return (
                <>
                    {goodValue}
                    {goodUnit} - {poorValue}
                    {poorUnit}
                </>
            )
        }

        if (band === 'good') {
            return (
                <>
                    &lt; {goodValue}
                    {goodUnit}
                </>
            )
        }

        return null
    }, [band, webVitalsTab])

    return (
        <div className="flex flex-row justify-between">
            {/* eslint-disable-next-line react/forbid-dom-props */}
            <span className="flex flex-row gap-1 items-center" style={{ color: WEB_VITALS_COLORS[band] }}>
                <Icon />
                {label}
            </span>
            <span className="text-sm text-muted">{thresholdText}</span>
        </div>
    )
}

const SKELETON_HEIGHT = {
    good: 'h-40',
    needs_improvements: 'h-60',
    poor: 'h-20',
} as const

const Content = ({
    band,
    response,
    responseLoading,
}: {
    band: WebVitalsMetricBand
    response: WebVitalsPathBreakdownQueryResponse | undefined
    responseLoading: boolean
}): JSX.Element => {
    const { webVitalsTab } = useValues(webAnalyticsLogic)

    const values = response?.results[0][band]
    const threshold = WEB_VITALS_THRESHOLDS[webVitalsTab]

    const loadedValues = values != null
    const hasNoValues = values?.length === 0

    return (
        <div className={clsx('pt-4', { 'h-full': loadedValues })}>
            <div className={clsx('flex flex-col gap-1', { 'justify-center': hasNoValues, 'h-full': loadedValues })}>
                {responseLoading ? (
                    <LemonSkeleton fade className={clsx('w-full', SKELETON_HEIGHT[band])} />
                ) : values?.length ? (
                    values?.map(({ path, value }) => {
                        const width = computeWidth(value, threshold)

                        return (
                            <div
                                className="flex flex-row items-center justify-between relative w-full p-2 py-1"
                                key={path}
                            >
                                <div
                                    className="absolute top-0 left-0 h-full"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ width, backgroundColor: 'var(--neutral-250)', opacity: 0.5 }}
                                />
                                <span className="relative z-10">{path}</span>
                                <span className="relative z-10">
                                    {value >= 1 ? value.toFixed(0) : value.toFixed(2)}
                                </span>
                            </div>
                        )
                    })
                ) : (
                    <div className="text-center">
                        <span>{band === 'good' ? '😿' : '🚀'}</span>
                        <span className="text-muted">No scores in this band</span>
                    </div>
                )}
            </div>
        </div>
    )
}

const computeWidth = (value: number, threshold: { good: number; poor: number }): string => {
    if (value < threshold.good) {
        return `${(value / threshold.good) * 100}%`
    }

    if (value > threshold.poor) {
        return `${((value - threshold.poor) / (threshold.good - threshold.poor)) * 100}%`
    }

    return `${((value - threshold.good) / (threshold.poor - threshold.good)) * 100}%`
}
