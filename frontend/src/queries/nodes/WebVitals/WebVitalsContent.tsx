import { IconInfo } from '@posthog/icons'
import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { useMemo } from 'react'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { WebVitalsQueryResponse } from '~/queries/schema/schema-general'

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
    WEB_VITALS_THRESHOLDS,
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

    const color = getThresholdColor(value, webVitalsTab)
    const band = getMetricBand(value, webVitalsTab)

    // NOTE: `band` will only return `none` if the value is undefined,
    // so this is basically the same check twice, but we need that to make TS happy
    if (value === undefined || band === 'none') {
        return <LemonSkeleton fade className="w-full h-40 rounded sm:w-[30%]" />
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
