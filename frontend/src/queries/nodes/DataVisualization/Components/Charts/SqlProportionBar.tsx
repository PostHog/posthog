import clsx from 'clsx'

import { ProportionBar } from '@posthog/quill-charts'
import type { ProportionBarConfig } from '@posthog/quill-charts'

import { useChartConfig } from 'lib/charts/hooks'

import { makeChartErrorHandler } from 'products/product_analytics/frontend/insights/trends/shared/chartErrorHandler'

import { SqlChartProps } from './SqlChart'
import { useSqlPartOfWholeChart } from './useSqlPartOfWholeChart'

const handleChartError = makeChartErrorHandler('sql-proportion-bar')

export const SqlProportionBar = ({
    xData,
    yData,
    chartSettings,
    presetChartHeight,
    className,
}: SqlChartProps): JSX.Element => {
    const { theme, series, legendConfig, total, showTotal, valueFormatter } = useSqlPartOfWholeChart(
        { xData, yData, chartSettings },
        true
    )
    const config: ProportionBarConfig = useChartConfig(() => ({ legend: legendConfig }), [legendConfig])

    if (!series.length) {
        return (
            <div className={clsx(className, 'rounded bg-surface-primary flex flex-1 items-center justify-center p-6')}>
                <span className="text-secondary text-sm">Proportion bars require at least one positive value.</span>
            </div>
        )
    }

    return (
        <div
            className={clsx(className, 'rounded bg-surface-primary flex flex-col flex-1 min-h-0 p-4 justify-center', {
                'h-[60vh]': presetChartHeight,
                'h-full': !presetChartHeight,
            })}
        >
            <ProportionBar
                series={series}
                theme={theme}
                config={config}
                valueFormatter={valueFormatter}
                dataAttr="sql-proportion-bar"
                onError={handleChartError}
            />
            {showTotal && (
                <div className="pt-4 text-center shrink-0">
                    <div className="text-5xl font-bold">{valueFormatter(total)}</div>
                </div>
            )}
        </div>
    )
}
