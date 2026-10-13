import { type ScatterChartConfig, type ScatterSeries } from '@posthog/quill-charts'

import { ChartSettings } from '~/queries/schema/schema-general'

import { AxisSeries, AxisSeriesSettings } from '../../dataVisualizationLogic'
import { formatSqlSeriesValue, hasAxisTickFormatting } from './sqlLineGraphAdapter'

/** Per-point display settings carried into quill's `meta` so the tooltip formats each point with its
 *  own column's currency/percent/prefix/suffix settings — the same trick the line path uses. */
export interface SqlScatterPointMeta {
    settings?: AxisSeriesSettings
}

export type SqlScatterSeries = ScatterSeries<SqlScatterPointMeta>

/** X values reach us as raw response cells — a number for an INTEGER column, a string for a DECIMAL.
 *  Anything that isn't a finite number can't be a coordinate. */
function toCoordinate(value: unknown): number | null {
    if (value === null || value === undefined || value === '') {
        return null
    }
    const parsed = typeof value === 'number' ? value : parseFloat(String(value))
    return Number.isFinite(parsed) ? parsed : null
}

/** Honors a column's custom display label, matching the line/bar path. `||` so a blank label falls
 *  through to the column name. */
const getSeriesLabel = (series: AxisSeries<number | null>): string =>
    series.settings?.display?.label || series.column.name

/**
 * One quill scatter series per selected Y column, each row of the result a point at
 * `(x column, y column)`. Rows missing either coordinate are dropped rather than zeroed: a scatter
 * has no ordering along x to interpolate a gap across, so a null is an absent reading, not a zero.
 */
export function buildScatterSeries(
    xData: AxisSeries<string> | null,
    yData: AxisSeries<number | null>[]
): SqlScatterSeries[] {
    if (!xData) {
        return []
    }

    return yData.map((series, index) => {
        const color = series.settings?.display?.color
        const points: SqlScatterSeries['points'] = []

        for (let row = 0; row < xData.data.length; row++) {
            const x = toCoordinate(xData.data[row])
            const y = toCoordinate(series.data[row])
            if (x === null || y === null) {
                continue
            }
            points.push({ x, y, meta: { settings: series.settings } })
        }

        return {
            key: `${series.column.name}-${index}`,
            label: getSeriesLabel(series),
            points,
            // Only pin an explicit color; otherwise let quill assign palette colors by index.
            ...(color ? { color } : {}),
        }
    })
}

export interface BuildScatterConfigArgs {
    xData: AxisSeries<string>
    yData: AxisSeries<number | null>[]
    chartSettings: ChartSettings
}

export function buildScatterConfig({
    xData,
    yData,
    chartSettings,
}: BuildScatterConfigArgs): ScatterChartConfig<SqlScatterPointMeta> {
    const yAxisSettings = chartSettings.leftYAxisSettings
    // Every series shares one gutter here (a scatter has no second axis), so the first column speaks
    // for the tick format — the same choice the line path makes per gutter.
    const tickSettings = yData[0]?.settings

    return {
        xAxis: {
            // Unlike a trend's self-describing date axis, a scatter's x is a measure, so fall back to
            // the column name rather than leaving the axis unlabeled.
            label: chartSettings.xAxisLabel || xData.column.name,
            scaleType: chartSettings.scatter?.xScale === 'logarithmic' ? 'log' : 'linear',
            // Neither axis starts at zero unless asked: both are independent measures, and forcing
            // one to zero squashes the cloud into a corner.
            startAtZero: chartSettings.scatter?.xStartAtZero ?? false,
            hide: chartSettings.showXAxisTicks === false,
        },
        yAxis: {
            label: yAxisSettings?.label,
            scaleType: yAxisSettings?.scale === 'logarithmic' ? 'log' : 'linear',
            startAtZero: yAxisSettings?.startAtZero ?? false,
            hide: yAxisSettings?.showTicks === false,
            tickFormatter: hasAxisTickFormatting(tickSettings)
                ? (value: number): string => formatSqlSeriesValue(value, tickSettings)
                : undefined,
        },
        showGrid: yAxisSettings?.showGridLines ?? true,
        showBestFit: chartSettings.scatter?.showBestFit ?? false,
        legend: {
            show: chartSettings.showLegend ?? false,
            position: chartSettings.legendPosition ?? 'top',
            interactive: true,
        },
        tooltip: {
            xFormatter: (value: number): string => value.toLocaleString(),
            yFormatter: (value: number, point): string => formatSqlSeriesValue(value, point.meta?.settings),
        },
    }
}
