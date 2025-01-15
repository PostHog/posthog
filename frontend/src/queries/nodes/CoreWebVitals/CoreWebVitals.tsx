import './CoreWebVitals.scss'

import { IconCheckCircle, IconInfo, IconWarning } from '@posthog/icons'
import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import { clsx } from 'clsx'
import { useActions, useValues } from 'kea'
import { IconExclamation } from 'lib/lemon-ui/icons'
import { useMemo, useState } from 'react'
import {
    CORE_WEB_VITALS_THRESHOLDS,
    CoreWebVitalsPercentile,
    CoreWebVitalsThreshold,
    webAnalyticsLogic,
} from 'scenes/web-analytics/webAnalyticsLogic'

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

type MetricBand = 'good' | 'improvements' | 'poor'

const LONG_METRIC_NAME: Record<CoreWebVitalsMetric, string> = {
    INP: 'Interaction to Next Paint',
    LCP: 'Largest Contentful Paint',
    FCP: 'First Contentful Paint',
    CLS: 'Cumulative Layout Shift',
}

const METRIC_DESCRIPTION: Record<CoreWebVitalsMetric, string> = {
    INP: 'Measures the time it takes for the user to interact with the page and for the page to respond to the interaction. Lower is better.',
    LCP: 'Measures how long it takes for the main content of a page to appear on screen. Lower is better.',
    FCP: 'Measures how long it takes for the initial text, non-white background, and non-white text to appear on screen. Lower is better.',
    CLS: 'Measures how much the layout of a page shifts around as content loads. Lower is better.',
}

const PERCENTILE_NAME: Record<CoreWebVitalsPercentile, string> = {
    p75: '75%',
    p90: '90%',
    p99: '99%',
}

const ICON_PER_BAND: Record<MetricBand, React.ElementType> = {
    good: IconCheckCircle,
    improvements: IconWarning,
    poor: IconExclamation,
}

const GRADE_PER_BAND: Record<MetricBand, string> = {
    good: 'Great',
    improvements: 'Needs Improvement',
    poor: 'Poor',
}

const POSITIONING_PER_BAND: Record<MetricBand, string> = {
    good: 'Below',
    improvements: 'Between',
    poor: 'Above',
}

const VALUES_PER_BAND: Record<MetricBand, (threshold: CoreWebVitalsThreshold) => number[]> = {
    good: (threshold) => [threshold.good],
    improvements: (threshold) => [threshold.good, threshold.poor],
    poor: (threshold) => [threshold.poor],
}

const QUANTIFIER_PER_BAND: Record<MetricBand, (coreWebVitalsPercentile: CoreWebVitalsPercentile) => string> = {
    good: (coreWebVitalsPercentile) => `More than ${PERCENTILE_NAME[coreWebVitalsPercentile]} of visits had`,
    improvements: (coreWebVitalsPercentile) =>
        `Some of the ${PERCENTILE_NAME[coreWebVitalsPercentile]} most performatic visits had`,
    poor: (coreWebVitalsPercentile) =>
        `Some of the ${PERCENTILE_NAME[coreWebVitalsPercentile]} most performatic visits had`,
}

const EXPERIENCE_PER_BAND: Record<MetricBand, string> = {
    good: 'a great experience',
    improvements: 'an experience that needs improvement',
    poor: 'a poor experience',
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

const getMetricBand = (value: number, threshold: CoreWebVitalsThreshold): MetricBand => {
    if (value <= threshold.good) {
        return 'good'
    }

    if (value <= threshold.poor) {
        return 'improvements'
    }

    return 'poor'
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

const CoreWebVitalsContent = ({
    coreWebVitalsQueryResponse,
}: {
    coreWebVitalsQueryResponse?: CoreWebVitalsQueryResponse
}): JSX.Element => {
    const { coreWebVitalsTab, coreWebVitalsPercentile } = useValues(webAnalyticsLogic)

    const value = useMemo(
        () => getMetric(coreWebVitalsQueryResponse?.results, coreWebVitalsTab, coreWebVitalsPercentile),
        [coreWebVitalsQueryResponse, coreWebVitalsPercentile, coreWebVitalsTab]
    )

    if (value === undefined) {
        return (
            <div className="w-full border rounded p-4 md:w-[30%]">
                <LemonSkeleton fade className="w-full h-40" />
            </div>
        )
    }

    const withMilliseconds = (values: number[]): string =>
        coreWebVitalsTab === 'CLS' ? values.join(' and ') : values.map((value) => `${value}ms`).join(' and ')

    const threshold = CORE_WEB_VITALS_THRESHOLDS[coreWebVitalsTab]
    const color = getThresholdColor(value, threshold)
    const band = getMetricBand(value, threshold)

    const grade = GRADE_PER_BAND[band]

    const Icon = ICON_PER_BAND[band]
    const positioning = POSITIONING_PER_BAND[band]
    const values = withMilliseconds(VALUES_PER_BAND[band](threshold))

    const quantifier = QUANTIFIER_PER_BAND[band](coreWebVitalsPercentile)
    const experience = EXPERIENCE_PER_BAND[band]

    return (
        <div className="w-full border rounded p-6 md:w-[30%] flex flex-col gap-2">
            <span className="text-lg">
                <strong>{LONG_METRIC_NAME[coreWebVitalsTab]}</strong>
            </span>

            <div className="flex flex-col">
                <Tooltip
                    title={
                        <div>
                            Great: Below {threshold.good}ms <br />
                            Needs Improvement: Between {threshold.good}ms and {threshold.poor}ms <br />
                            Poor: Above {threshold.poor}ms
                        </div>
                    }
                >
                    <strong>{grade}</strong>
                    <IconInfo className="inline-block ml-1" />
                </Tooltip>

                <span>
                    <Icon className={clsx('inline-block mr-1', `text-${color}`)} />
                    {positioning} {values}
                </span>
            </div>

            <div className="text-xs text-muted-foreground">
                {quantifier} {experience}
            </div>

            <hr className="my-2" />

            <span>{METRIC_DESCRIPTION[coreWebVitalsTab]}</span>
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
const getThresholdColor = (value: number | undefined, threshold: CoreWebVitalsThreshold): Color => {
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
    setTab?: () => void
    inSeconds?: boolean
}): JSX.Element {
    // TODO: Go back to using an actual value
    // Will keep this as is while we test what the UI looks like
    // const {value: parsedValue, unit } = getValueWithUnit(value, inSeconds)
    const newValue = true ? (inSeconds ? Math.random() * 10000 : Math.random()) : value
    const { value: parsedValue, unit } = getValueWithUnit(newValue, inSeconds)

    const threshold = CORE_WEB_VITALS_THRESHOLDS[metric]
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
    threshold: CoreWebVitalsThreshold
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
                className={clsx('absolute h-full rounded-full', isGood ? 'bg-success' : 'bg-muted')}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ width: `${goodWidth}%` }}
            />

            {/* Yellow segment up to "poor" threshold */}
            <div
                className={clsx('absolute h-full rounded-full', isAverage ? 'bg-warning' : 'bg-muted')}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ left: `${goodWidth + 1}%`, width: `${averageWidth - 1}%` }}
            />

            {/* Red segment after "poor" threshold */}
            <div
                className={clsx('absolute h-full rounded-full', isPoor ? 'bg-danger' : 'bg-muted')}
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
