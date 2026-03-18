import { useValues } from 'kea'
import { useMemo } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { WebVitalsQueryResponse } from '~/queries/schema/schema-general'

import {
    EXPERIENCE_PER_BAND,
    GRADE_PER_BAND,
    ICON_PER_BAND,
    LONG_METRIC_NAME,
    METRIC_DESCRIPTION,
    POSITIONING_PER_BAND,
    QUANTIFIER_PER_BAND,
    VALUES_PER_BAND,
    WEB_VITALS_THRESHOLDS,
    getMetric,
    getMetricBand,
    getThresholdColor,
} from './definitions'

type WebVitalsContentProps = {
    webVitalsQueryResponse?: WebVitalsQueryResponse
    isLoading: boolean
}

export const WebVitalsContent = ({ webVitalsQueryResponse, isLoading }: WebVitalsContentProps): JSX.Element => {
    const { webVitalsTab, webVitalsPercentile } = useValues(webAnalyticsLogic)

    const value = useMemo(
        () => getMetric(webVitalsQueryResponse?.results, webVitalsTab, webVitalsPercentile),
        [webVitalsQueryResponse, webVitalsPercentile, webVitalsTab]
    )

    const withMilliseconds = (values: number[]): string =>
        webVitalsTab === 'CLS' ? values.join(' and ') : values.map((value) => `${value}ms`).join(' and ')

    const color = getThresholdColor(value, webVitalsTab)
    const band = getMetricBand(value, webVitalsTab)

    // Show skeleton only when loading
    if (isLoading) {
        return <LemonSkeleton fade className="w-full h-full rounded sm:w-[30%]" />
    }

    // Show no data message when not loading and value is undefined
    if (value === undefined || band === 'none') {
        return (
            <div className="w-full p-4 sm:w-[30%] flex flex-col gap-2 bg-surface-primary rounded border items-center justify-center">
                <span className="text-sm text-text-tertiary">No data for the selected date range</span>
            </div>
        )
    }

    const grade = GRADE_PER_BAND[band]
    const threshold = WEB_VITALS_THRESHOLDS[webVitalsTab]

    const Icon = ICON_PER_BAND[band]
    const positioning = POSITIONING_PER_BAND[band]
    const values = withMilliseconds(VALUES_PER_BAND[band](threshold))

    const quantifier = QUANTIFIER_PER_BAND[band](webVitalsPercentile)
    const experience = EXPERIENCE_PER_BAND[band]

    const unit = webVitalsTab === 'CLS' ? '' : 'ms'

    return (
        <div className="w-full p-4 sm:w-[30%] flex flex-col gap-2 bg-surface-primary rounded border">
            <span className="text-lg">
                <strong>{LONG_METRIC_NAME[webVitalsTab]}</strong>
            </span>

            <div className="flex flex-col">
                <Tooltip
                    title={
                        <div>
                            Great: Below {threshold.good}
                            {unit} <br />
                            Needs Improvement: Between {threshold.good}
                            {unit} and {threshold.poor}
                            {unit} <br />
                            Poor: Above {threshold.poor}
                            {unit}
                        </div>
                    }
                >
                    <strong>{grade}</strong>
                    <IconInfo className="inline-block ml-1" />
                </Tooltip>

                <span>
                    <Icon className="inline-block mr-1" style={{ color }} />
                    {positioning} {values}
                </span>
            </div>

            <div className="text-xs text-secondary-foreground">
                {quantifier} {experience}
            </div>

            <hr className="my-2" />

            <span>{METRIC_DESCRIPTION[webVitalsTab]}</span>
        </div>
    )
}
