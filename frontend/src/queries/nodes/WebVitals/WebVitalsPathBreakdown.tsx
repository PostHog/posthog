import clsx from 'clsx'
import { BuiltLogic, LogicWrapper, useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { parseAliasToReadable } from 'lib/components/PathCleanFilters/PathCleanFilterItem'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import {
    AnyResponseType,
    WebVitalsMetricBand,
    WebVitalsPathBreakdownQuery,
    WebVitalsPathBreakdownQueryResponse,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { PropertyFilterType } from '~/types'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'
import {
    ICON_PER_BAND,
    WEB_VITALS_COLORS,
    WEB_VITALS_THRESHOLDS,
    computePositionInBand,
    getValueWithUnit,
} from './definitions'

let uniqueNode = 0
export function WebVitalsPathBreakdown(props: {
    query: WebVitalsPathBreakdownQuery
    cachedResults?: AnyResponseType
    context: QueryContext
    attachTo?: LogicWrapper | BuiltLogic
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

    useAttachedLogic(logic, props.attachTo)

    const { response, responseLoading } = useValues(logic)

    // Properly type it before passing to Content
    const webVitalsQueryResponse = response as WebVitalsPathBreakdownQueryResponse | undefined

    return (
        <div className="border rounded bg-surface-primary grid grid-cols-1 md:grid-cols-3 divide-y md:divide-y-0 md:divide-x min-h-60 h-full">
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
    )
}

const Header = ({ band, label }: { band: WebVitalsMetricBand; label: string }): JSX.Element => {
    const { webVitalsTab } = useValues(webAnalyticsLogic)

    const Icon = ICON_PER_BAND[band]

    const thresholdText = useMemo(() => {
        const threshold = WEB_VITALS_THRESHOLDS[webVitalsTab]

        const { value: poorValue, unit: poorUnit } = getValueWithUnit(threshold.poor, webVitalsTab)
        const { value: goodValue, unit: goodUnit } = getValueWithUnit(threshold.good, webVitalsTab)

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
            <span className="flex flex-row gap-1 items-center font-semibold" style={{ color: WEB_VITALS_COLORS[band] }}>
                <Icon className="w-6 h-6" />
                {label}
            </span>
            <span className="text-sm text-secondary">{thresholdText}</span>
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
    const { webVitalsTab, isPathCleaningEnabled } = useValues(webAnalyticsLogic)
    const { togglePropertyFilter } = useActions(webAnalyticsLogic)

    const values = response?.results[0][band]

    const loadedValues = values != null
    const hasNoValues = values?.length === 0

    return (
        <div className={clsx('pt-4', { 'h-full': loadedValues })}>
            <div className={clsx('flex flex-col gap-1', { 'justify-center': hasNoValues, 'h-full': loadedValues })}>
                {responseLoading ? (
                    <LemonSkeleton fade className={clsx('w-full', SKELETON_HEIGHT[band])} />
                ) : values?.length ? (
                    values?.map(({ path, value }) => {
                        const width = computePositionInBand(value, webVitalsTab) * 100

                        const { value: parsedValue, unit } = getValueWithUnit(value, webVitalsTab)

                        return (
                            <div
                                className="flex flex-row items-center justify-between relative w-full p-2 py-1"
                                key={path}
                            >
                                <div
                                    className="absolute top-0 left-0 h-full opacity-80 bg-surface-secondary"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ width }}
                                />
                                <span
                                    title={path}
                                    className="relative z-10 truncate mr-2 flex-1 cursor-pointer hover:underline"
                                    onClick={() => {
                                        togglePropertyFilter(PropertyFilterType.Event, '$pathname', path)
                                    }}
                                >
                                    {isPathCleaningEnabled ? parseAliasToReadable(path) : path}
                                </span>
                                <span className="relative z-10 flex-shrink-0">
                                    {parsedValue}
                                    {unit}
                                </span>
                            </div>
                        )
                    })
                ) : (
                    <div className="text-center">
                        <span>{band === 'good' ? '😿' : '🚀'}</span>
                        <span className="text-secondary">No scores in this band</span>
                    </div>
                )}
            </div>
        </div>
    )
}
