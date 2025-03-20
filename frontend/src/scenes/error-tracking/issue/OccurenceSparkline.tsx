import { ScaleOptions } from 'chart.js'
import { TimeUnit } from 'chart.js'
import { useValues } from 'kea'
import { Sparkline } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { useCallback, useMemo } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { ErrorTrackingIssueAggregations, ErrorTrackingSparklineConfig } from '~/queries/schema/schema-general'

import { errorTrackingLogic } from '../errorTrackingLogic'
import { sparklineLabels } from '../utils'

export function OccurenceSparkline({
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

    const withXScale = useCallback(
        (scale: ScaleOptions) => {
            return {
                ...scale,
                type: 'timeseries',
                ticks: {
                    display: true,
                    maxRotation: 0,
                    maxTicksLimit: 5,
                },
                time: {
                    unit: unit,
                    displayFormats: {
                        hour: 'HH:mm',
                        minute: 'HH:mm',
                        day: 'D MMM YYYY',
                        week: 'D MMM YYYY',
                        month: 'MMM YYYY',
                        year: 'YYYY',
                    },
                },
            } as ScaleOptions
        },
        [unit]
    )

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
            color: isDarkModeOn ? 'primitive-neutral-200' : 'primitive-neutral-800',
            hoverColor: 'primary-3000',
        }
    }, [isDarkModeOn])
}

export function useSparklineData(aggregations?: ErrorTrackingIssueAggregations): [number[], TimeUnit, number] {
    const { sparklineSelectedPeriod, customSparklineConfig } = useValues(errorTrackingLogic)
    const [values, unit, interval]: [number[], TimeUnit, number] = useMemo(() => {
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
    return [values, unit, interval]
}

function wrapDataWithColor(data: any[] | null, colors: { color: string; hoverColor: string }): any[] {
    return [
        {
            values: data || [],
            name: 'Occurences',
            ...colors,
        },
    ]
}
