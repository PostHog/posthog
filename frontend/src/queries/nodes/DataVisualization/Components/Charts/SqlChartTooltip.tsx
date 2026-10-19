import { DefaultTooltip, TooltipConfig, TooltipContext } from '@posthog/quill-charts'

import { SqlChartProps } from './SqlChart'
import { SqlLineSeriesMeta, formatSqlSeriesValue } from './sqlLineGraphAdapter'

export function SqlChartTooltip({
    context,
    config,
    onPointClick,
    hint,
}: {
    context: TooltipContext<SqlLineSeriesMeta>
    config?: TooltipConfig
    onPointClick: NonNullable<SqlChartProps['onPointClick']>
    hint?: string
}): JSX.Element {
    return (
        <DefaultTooltip
            {...context}
            valueFormatter={
                config?.valueFormatter ?? ((value, entry) => formatSqlSeriesValue(value, entry.series.meta?.settings))
            }
            labelFormatter={config?.labelFormatter}
            showTotal={config?.showTotal}
            totalFormatter={config?.totalFormatter}
            sortedByValue
            footer={hint ?? 'Click a series to inspect'}
            onRowClick={(entry) => {
                context.onUnpin?.()
                onPointClick(entry.series.key, context.dataIndex, context.label)
            }}
        />
    )
}
