import { z } from 'zod'

// A generative-UI chart spec: a flat, declarative description of a chart that an LLM can emit and
// `ChartSpecRenderer` turns into a `@posthog/quill-charts` component. Every field carries a
// `.describe()` so the same schema can be handed to a model as a structured-output contract.

const valueFormat = z
    .enum(['numeric', 'short', 'percentage', 'percentage_scaled', 'currency', 'duration', 'duration_ms'])
    .describe(
        "How to format values on this axis/series. 'percentage' expects 0–100, 'percentage_scaled' expects 0–1, " +
            "'duration' expects seconds, 'duration_ms' expects milliseconds, 'short' compacts large numbers (1.2k)."
    )

export const chartSpecAxisSchema = z
    .object({
        id: z.enum(['left', 'right']).describe('Which side this axis is on. Series target it via `series.axis`.'),
        label: z.string().optional().describe('Axis title shown beside the axis.'),
        format: valueFormat.optional().describe('Default numeric formatting for ticks on this axis.'),
        currency: z.string().optional().describe("ISO currency code (e.g. 'USD') when format is 'currency'."),
        scale: z.enum(['linear', 'log']).optional().describe("Scale type. Defaults to 'linear'."),
        startAtZero: z
            .boolean()
            .optional()
            .describe('Clamp the baseline to zero (default true). Set false to float the axis to the data range.'),
    })
    .describe('A value axis. Provide two (left + right) for a dual-axis chart.')

export const chartSpecSeriesSchema = z
    .object({
        key: z.string().describe('Stable unique identifier for the series.'),
        label: z.string().describe('Human-readable name shown in legend and tooltip.'),
        data: z.array(z.number()).describe('One value per x-axis label. Must match `labels` length.'),
        color: z
            .string()
            .optional()
            .describe('CSS color. Omit to auto-assign from the on-brand data palette by index.'),
        type: z
            .enum(['line', 'bar', 'area'])
            .optional()
            .describe('For combo charts only: how to draw this series. Ignored by single-type charts.'),
        axis: z
            .enum(['left', 'right'])
            .optional()
            .describe("Which axis to scale against. Defaults to 'left'. Use 'right' for a second axis."),
        fill: z.boolean().optional().describe('Fill the area under a line (line charts). Ignored for bars.'),
        dashed: z.boolean().optional().describe('Render the line dashed — handy for forecasts or targets.'),
    })
    .describe('A single data series.')

export const chartSpecReferenceLineSchema = z
    .object({
        value: z
            .union([z.number(), z.string()])
            .describe('A numeric value (horizontal line) or an x-axis label (vertical marker).'),
        orientation: z.enum(['horizontal', 'vertical']).optional().describe("Defaults to 'horizontal'."),
        label: z.string().optional().describe('Text label drawn on the line.'),
        variant: z
            .enum(['goal', 'alert', 'marker'])
            .optional()
            .describe("Visual style: 'goal' (dashed grey), 'alert' (dashed red), 'marker' (solid thin)."),
        axis: z.enum(['left', 'right']).optional().describe('Which axis a horizontal line is measured against.'),
    })
    .describe('An annotation line: a goal/threshold (horizontal) or an event marker (vertical).')

export const chartSpecConfigSchema = z
    .object({
        // Layout
        stacked: z.boolean().optional().describe('Stack series (bar/area).'),
        grouped: z.boolean().optional().describe('Group bars side by side instead of stacking.'),
        percent: z.boolean().optional().describe('Normalize the stack to 100%.'),
        horizontal: z.boolean().optional().describe('Bar charts only: lay bars out horizontally (ranked list).'),
        donut: z.boolean().optional().describe('Pie charts only: render as a donut (innerRadiusRatio 0.6).'),
        innerRadiusRatio: z
            .number()
            .min(0)
            .max(0.95)
            .optional()
            .describe(
                'Pie charts: inner radius as a fraction (0 = pie, 0.4–0.7 = donut ring, 0.85 = thin ring). Overrides donut.'
            ),

        // Legend
        showLegend: z.boolean().optional().describe('Show an interactive legend.'),
        legendPosition: z
            .enum(['top', 'bottom', 'left', 'right'])
            .optional()
            .describe("Where the legend sits relative to the plot. Default 'bottom'."),
        legendAlign: z
            .enum(['start', 'center', 'end'])
            .optional()
            .describe("Legend alignment along its axis. Default 'center'."),

        // Overlays
        showGrid: z.boolean().optional().describe('Show horizontal grid lines.'),
        showAxisLines: z
            .boolean()
            .optional()
            .describe('Show L-shaped axis baselines only (no interior grid). Ignored when showGrid is true.'),
        showCrosshair: z.boolean().optional().describe('Show a vertical crosshair line following the cursor.'),
        showValueLabels: z.boolean().optional().describe('Draw the value of each point/bar on the chart.'),

        // Axes
        hideXAxis: z.boolean().optional().describe('Hide x-axis labels and reduce bottom margin.'),
        hideYAxis: z.boolean().optional().describe('Hide y-axis labels and reduce left margin.'),

        // Tooltip
        tooltipShowTotal: z
            .boolean()
            .optional()
            .describe('Show a total row at the bottom of the tooltip. Useful for stacked charts.'),
        tooltipPlacement: z
            .enum(['follow-data', 'top', 'cursor'])
            .optional()
            .describe(
                "Tooltip anchor: 'follow-data' (default, tracks highest point), 'top' (fixed), 'cursor' (beside mouse)."
            ),

        // Bar-specific
        barFillStyle: z
            .enum(['flat', 'gradient', 'gloss'])
            .optional()
            .describe("Bar fill treatment. 'flat' (default), 'gradient' (diagonal sheen), 'gloss' (radial highlight)."),
        divergingStack: z
            .boolean()
            .optional()
            .describe('Stacked bar charts: stack negative values below the zero baseline.'),
        roundStackEnds: z
            .boolean()
            .optional()
            .describe('Stacked bar charts: round both outer ends of the whole stack as a pill.'),

        // MetricCard-specific
        showChange: z.boolean().optional().describe('Metric card: show a change/trend pill.'),
        goodDirection: z
            .enum(['up', 'down'])
            .optional()
            .describe("Metric card: which direction is good ('up' = higher is better, 'down' = lower is better)."),
        changeInline: z
            .boolean()
            .optional()
            .describe('Metric card: render the change pill beside the headline instead of in the header row.'),
        sparklineFill: z
            .boolean()
            .optional()
            .describe("Metric card: fill the card's remaining height with the sparkline."),
        subtitle: z.string().optional().describe('Metric card: caption shown under the headline.'),
    })
    .describe('Layout and decoration toggles.')

export const chartSpecSchema = z
    .object({
        chartType: z
            .enum(['line', 'bar', 'combo', 'timeSeriesLine', 'timeSeriesBar', 'pie', 'metricCard'])
            .describe(
                'The chart family. Use `timeSeriesLine` or `timeSeriesBar` when x labels are ISO date strings ' +
                    '(they format dates properly); `bar`/`line` for categorical x-axes; `combo` to mix bars and lines; ' +
                    '`metricCard` for a single headline number with a sparkline.'
            ),
        title: z.string().optional().describe('Short chart title.'),
        narrative: z
            .string()
            .optional()
            .describe('One sentence on what this chart shows and why it was chosen — surfaced to the user.'),
        labels: z
            .array(z.string())
            .describe('X-axis labels (ISO date strings for `timeSeriesLine`). Same length as each series `data`.'),
        series: z.array(chartSpecSeriesSchema).min(1).describe('The series to plot.'),
        axes: z.array(chartSpecAxisSchema).optional().describe('Axis definitions. Provide two for a dual-axis chart.'),
        config: chartSpecConfigSchema.optional(),
        referenceLines: z.array(chartSpecReferenceLineSchema).optional().describe('Goal lines and event markers.'),
    })
    .describe('A complete, renderable chart described declaratively.')

export type ChartSpec = z.infer<typeof chartSpecSchema>
export type ChartSpecSeries = z.infer<typeof chartSpecSeriesSchema>
export type ChartSpecAxis = z.infer<typeof chartSpecAxisSchema>
export type ChartSpecReferenceLine = z.infer<typeof chartSpecReferenceLineSchema>
export type ChartSpecConfig = z.infer<typeof chartSpecConfigSchema>
export type ChartSpecValueFormat = z.infer<typeof valueFormat>
