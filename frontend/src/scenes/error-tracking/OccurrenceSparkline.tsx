import { useValues } from 'kea'
import { AnyScaleOptions, Sparkline } from 'lib/components/Sparkline'
import { dayjs } from 'lib/dayjs'
import { useCallback, useMemo } from 'react'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { DateRange, ErrorTrackingIssueAggregations } from '~/queries/schema/schema-general'

import { SparklineSelectedPeriod } from './errorTrackingSceneLogic'
import { generateSparklineLabels } from './utils'

export function OccurrenceSparkline({
    values,
    labels,
    className,
    displayXAxis = false,
    loading = false,
}: {
    values: number[]
    labels: string[]
    className?: string
    displayXAxis?: boolean
    loading?: boolean
}): JSX.Element {
    const colors = useSparklineColors()

    const [data, labelRenderer] = useMemo(() => {
        return [
            wrapDataWithColor(values, colors),
            (label: string) => {
                return dayjs(label).format('D MMM YYYY HH:mm (UTC)')
            },
        ]
    }, [values, colors])

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
            loading={loading}
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

export function useSparklineData(
    selectedPeriod: SparklineSelectedPeriod = 'day',
    dateRange: DateRange,
    aggregations?: ErrorTrackingIssueAggregations
): { values: number[]; labels: string[] } {
    const result = useMemo(() => {
        if (!aggregations) {
            return { values: [], labels: [] }
        }

        const { values, aggregationDateRange } = {
            day: {
                values: aggregations.volumeDay,
                aggregationDateRange: { date_from: '-24h' },
            },
            custom: {
                values: aggregations.volumeRange,
                aggregationDateRange: dateRange,
            },
        }[selectedPeriod]

        const resolution = values.length
        const labels = generateSparklineLabels(aggregationDateRange, resolution)

        return { values, labels }
    }, [aggregations, selectedPeriod, dateRange])

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
