import type { Series } from '@posthog/quill-charts'

export function dimChartColor(color: string): string {
    return `color-mix(in srgb, ${color} 25%, transparent)`
}

export function highlightChartSeries<Meta>(
    series: Series<Meta>[],
    colors: string[],
    isSelected?: (seriesKey: string, dataIndex: number) => boolean
): Series<Meta>[] {
    if (!isSelected) {
        return series
    }
    return series.map((item, index) => {
        const color = item.color || colors[index % colors.length]
        return {
            ...item,
            color: item.type === 'bar' ? color : dimChartColor(color),
            bars: item.data.map((_, dataIndex) => {
                const bar = item.bars?.[dataIndex]
                const barColor = bar?.color || color
                return { ...bar, color: isSelected(item.key, dataIndex) ? barColor : dimChartColor(barColor) }
            }),
        }
    })
}
