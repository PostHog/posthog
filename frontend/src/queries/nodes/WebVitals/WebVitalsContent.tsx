import { IconInfo } from '@posthog/icons'
import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues } from 'kea'
import { useMemo } from 'react'
import { WEB_VITALS_THRESHOLDS, webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { WebVitalsQueryResponse } from '~/queries/schema'

import {
    EXPERIENCE_PER_BAND,
    getMetric,
    getMetricBand,
    getThresholdColor,
    GRADE_PER_BAND,
    ICON_PER_BAND,
    LONG_METRIC_NAME,
    METRIC_DESCRIPTION,
    POSITIONING_PER_BAND,
    QUANTIFIER_PER_BAND,
    VALUES_PER_BAND,
} from './definitions'

type WebVitalsContentProps = {
    webVitalsQueryResponse?: WebVitalsQueryResponse
}

export const WebVitalsContent = ({ webVitalsQueryResponse }: WebVitalsContentProps): JSX.Element => {
    const { webVitalsTab, webVitalsPercentile } = useValues(webAnalyticsLogic)

    const value = useMemo(
        () => getMetric(webVitalsQueryResponse?.results, webVitalsTab, webVitalsPercentile),
        [webVitalsQueryResponse, webVitalsPercentile, webVitalsTab]
    )

    const withMilliseconds = (values: number[]): string =>
        webVitalsTab === 'CLS' ? values.join(' and ') : values.map((value) => `${value}ms`).join(' and ')

    const threshold = WEB_VITALS_THRESHOLDS[webVitalsTab]
    const color = getThresholdColor(value, threshold)
    const band = getMetricBand(value, threshold)

    // NOTE: `band` will only return `none` if the value is undefined,
    // so this is basically the same check twice, but we need that to make TS happy
    if (value === undefined || band === 'none') {
        return (
            <div className="w-full border rounded p-4 md:w-[30%]">
                <LemonSkeleton fade className="w-full h-40" />
            </div>
        )
    }

    const grade = GRADE_PER_BAND[band]

    const Icon = ICON_PER_BAND[band]
    const positioning = POSITIONING_PER_BAND[band]
    const values = withMilliseconds(VALUES_PER_BAND[band](threshold))

    const quantifier = QUANTIFIER_PER_BAND[band](webVitalsPercentile)
    const experience = EXPERIENCE_PER_BAND[band]

    return (
        <div className="w-full border rounded p-6 md:w-[30%] flex flex-col gap-2">
            <span className="text-lg">
                <strong>{LONG_METRIC_NAME[webVitalsTab]}</strong>
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

            <span>{METRIC_DESCRIPTION[webVitalsTab]}</span>
        </div>
    )
}
