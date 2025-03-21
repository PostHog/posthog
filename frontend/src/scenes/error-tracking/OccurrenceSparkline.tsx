import { TimeUnit } from 'chart.js'
import { useValues } from 'kea'
import { AnyScaleOptions, Sparkline } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { useCallback, useMemo } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { ErrorTrackingIssueAggregations, ErrorTrackingSparklineConfig } from '~/queries/schema/schema-general'

import { errorTrackingLogic } from './errorTrackingLogic'
import { sparklineLabels } from './utils'

export function OccurrenceSparkline({
    values,
    unit,
    interval,
    className,
    displayXAxis = false,
}: {
    values: number[]
    unit: TimeUnit
    interval: number
    className?: string
    displayXAxis?: boolean
}): JSX.Element {
    const colors = useSparklineColors()

    const [data, labels, labelRenderer] = useMemo(() => {
        return [
            wrapDataWithColor(values, colors),
            sparklineLabels({ value: interval, interval: unit } as ErrorTrackingSparklineConfig),
            (label: string) => {
                switch (unit) {
                    case 'hour':
                    case 'minute':
                        return dayjs(label).format('D MMM YYYY HH:mm (UTC)')
                    case 'day':
                        return dayjs(label).format('D MMM YYYY (UTC)')
                    case 'week':
                        return dayjs(label).format('D MMM YYYY (UTC)')
                    case 'month':
                        return dayjs(label).format('MMM YYYY (UTC)')
                    default:
                        return dayjs(label).format('D MMM YYYY (UTC)')
                }
            },
        ]
    }, [values, unit, interval, colors])

    const withXScale = useCallback((scale: AnyScaleOptions) => {
        return {
            ...scale,
            type: 'timeseries',
            ticks: {
                display: true,
                maxRotation: 0,
                maxTicksLimit: 5,
                font: {
                    size: 10,
                    lineHeight: 1,
                },
            },
            time: {
                unit: 'day',
                displayFormats: {
                    day: 'D MMM',
                },
            },
        } as AnyScaleOptions
    }, [])

    return (
        <Sparkline
            className={className}
            data={data}
            labels={labels}
            renderLabel={labelRenderer}
            withXScale={displayXAxis ? withXScale : undefined}
        />
    )
}

function useSparklineColors(): { color: string; hoverColor: string } {
    const { isDarkModeOn } = useValues(themeLogic)

    return useMemo(() => {
        return {
            color: isDarkModeOn ? 'primitive-neutral-800' : 'primitive-neutral-200',
            hoverColor: isDarkModeOn ? 'primitive-neutral-200' : 'primitive-neutral-800',
        }
    }, [isDarkModeOn])
}

export function useSparklineData(aggregations?: ErrorTrackingIssueAggregations): [number[], TimeUnit, number] {
    const { sparklineSelectedPeriod, customSparklineConfig } = useValues(errorTrackingLogic)

    const result: [number[], TimeUnit, number] = useMemo(() => {
        if (!aggregations) {
            return [[], 'hour', 0]
        }
        switch (sparklineSelectedPeriod) {
            case '24h':
                return [aggregations.volumeDay, 'hour', 24]
            case '30d':
                return [aggregations.volumeMonth, 'day', 31]
            default:
                if (customSparklineConfig && aggregations.customVolume) {
                    return [aggregations.customVolume, customSparklineConfig.interval, customSparklineConfig.value]
                }
        }
        return [[], 'hour', 0]
    }, [aggregations, customSparklineConfig, sparklineSelectedPeriod])

    return result
}

function wrapDataWithColor(data: any[] | null, colors: { color: string; hoverColor: string }): any[] {
    return [
        {
            values: data || [],
            name: 'Occurrences',
            ...colors,
        },
    ]
}
