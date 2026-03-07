/**
 * HogCharts — A charting library for PostHog data.
 *
 * @example Quick start
 * ```tsx
 * import { Line, Bar, Pie, Funnel, Number, HogChart } from 'lib/hog-charts'
 *
 * // Typed chart component
 * <Line
 *     data={[{ label: 'Users', data: [100, 200, 300, 250] }]}
 *     labels={['Mon', 'Tue', 'Wed', 'Thu']}
 * />
 *
 * // Universal component (type determined at runtime)
 * <HogChart type="bar" data={data} labels={labels} />
 *
 * // Big KPI number with comparison
 * <Number value={42069} previousValue={38000} label="Weekly active users" />
 *
 * // Funnel
 * <Funnel steps={[
 *     { label: 'Visit', count: 10000 },
 *     { label: 'Sign up', count: 3000 },
 *     { label: 'Purchase', count: 400 },
 * ]} />
 * ```
 */

// -- Chart components -------------------------------------------------------
export { Area } from './components/Area'
export { Bar } from './components/Bar'
export { BoxPlot } from './components/BoxPlot'
export { Funnel } from './components/Funnel'
export { Heatmap } from './components/Heatmap'
export { HogChart } from './components/HogChart'
export { Lifecycle } from './components/Lifecycle'
export { Line } from './components/Line'
export { Number } from './components/Number'
export { Paths } from './components/Paths'
export { Pie } from './components/Pie'
export { Retention } from './components/Retention'
export { WorldMap } from './components/WorldMap'

// -- Tooltip ----------------------------------------------------------------
export { DefaultTooltip } from './components/Tooltip'

// -- Theme & colors ---------------------------------------------------------
export { defaultTheme, hogColors, lifecycleColors, mergeTheme, seriesColor } from './theme'

// -- Formatting utilities ---------------------------------------------------
export { computeDelta, formatValue } from './format'

// -- Types ------------------------------------------------------------------
export type {
    Annotation,
    AreaProps,
    AxisConfig,
    AxisFormat,
    AxisScale,
    BarOrientation,
    BarProps,
    BaseChartProps,
    BoxPlotDatum,
    BoxPlotProps,
    ClickEvent,
    ComparisonSeries,
    FunnelLayout,
    FunnelProps,
    FunnelStep,
    FunnelVizType,
    GoalLine,
    HeatmapCell,
    HeatmapProps,
    HogChartProps,
    HogChartTheme,
    LegendConfig,
    LegendPosition,
    LifecycleBucket,
    LifecycleProps,
    LifecycleStatus,
    LineInterpolation,
    LineProps,
    LineStyle,
    MapDataPoint,
    NumberProps,
    PathLink,
    PathNode,
    PathsProps,
    PieProps,
    PieSlice,
    RetentionCohort,
    RetentionPeriod,
    RetentionProps,
    Series,
    StickinessProps,
    TimeSeriesProps,
    TooltipConfig,
    TooltipContext,
    TooltipPoint,
    WorldMapProps,
} from './types'
