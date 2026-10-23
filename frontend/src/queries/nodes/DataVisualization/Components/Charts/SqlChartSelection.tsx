import { AnomalyPointsLayer, useChartLayout } from '@posthog/quill-charts'

export function SqlChartSelection({
    isSelected,
    colors,
}: {
    isSelected?: (seriesKey: string, dataIndex: number) => boolean
    colors: string[]
}): JSX.Element | null {
    const { series, resolvePositionValue } = useChartLayout()
    if (!isSelected) {
        return null
    }
    return (
        <>
            {series.map((item, seriesIndex) =>
                item.type === 'bar' ? null : (
                    <AnomalyPointsLayer
                        key={item.key}
                        radius={5}
                        markers={item.data.flatMap((value, dataIndex) =>
                            Number.isFinite(value) && isSelected(item.key, dataIndex)
                                ? [
                                      {
                                          dataIndex,
                                          value: resolvePositionValue(item, dataIndex),
                                          yAxisId: item.yAxisId ?? 'left',
                                          color: colors[seriesIndex],
                                      },
                                  ]
                                : []
                        )}
                    />
                )
            )}
        </>
    )
}
