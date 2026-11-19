import { z } from 'zod'

import { CALCS } from './legend'

declare module 'zod' {
    interface GlobalMeta {
        group?: string
        labels?: Record<string, string>
        showIf?: (o: Record<string, any>) => boolean
        range?: [number, number]
    }
}

export const REDUCERS = ['last', 'first', 'sum', 'mean', 'max', 'min', 'count'] as const
const reduceOpt = z
    .enum(REDUCERS)
    .default('last')
    .meta({ title: 'Calculation', description: 'How each series becomes one value', group: 'Value' })
const legendOpt = (
    first: 'bottom' | 'right'
): z.ZodDefault<z.ZodEnum<{ bottom: 'bottom'; right: 'right'; none: 'none' }>> =>
    z
        .enum(first === 'bottom' ? ['bottom', 'right', 'none'] : ['right', 'bottom', 'none'])
        .default(first)
        .meta({ title: 'Legend', group: 'Legend', labels: { none: 'Hidden' } })

export const timeseries = z.object({
    style: z.enum(['line', 'bars', 'points']).default('line').meta({ title: 'Draw as', group: 'Graph' }),
    area: z.boolean().default(false).meta({ title: 'Fill area', description: 'Shade under each line', group: 'Graph' }),
    stack: z.boolean().default(false).meta({ title: 'Stack series', group: 'Graph' }),
    seriesOrder: z
        .enum(['query', 'name', 'total'])
        .default('query')
        .meta({
            title: 'Series order',
            description: 'How series stack, take colours and list in the legend',
            group: 'Graph',
            labels: { query: 'As queried', name: 'By name', total: 'Biggest first' },
        }),
    percent: z
        .boolean()
        .default(false)
        .meta({
            title: '100% stacked',
            description: 'Each series as its share of the total at that time',
            group: 'Graph',
            showIf: (o) => o.stack,
        }),
    gradient: z
        .boolean()
        .default(false)
        .meta({
            title: 'Gradient fill',
            description: 'Areas fade towards the axis',
            group: 'Graph',
            showIf: (o) => o.area && !o.stack,
        }),
    curve: z
        .enum(['linear', 'monotone'])
        .default('monotone')
        .meta({
            title: 'Line',
            group: 'Graph',
            labels: { monotone: 'Smooth', linear: 'Straight' },
            showIf: (o) => o.style !== 'bars',
        }),
    points: z
        .boolean()
        .default(false)
        .meta({ title: 'Show points', group: 'Graph', showIf: (o) => o.style === 'line' }),
    lineWidth: z
        .number()
        .min(0)
        .max(10)
        .optional()
        .meta({
            title: 'Line width',
            description: 'In pixels (default 2; 0 = no line). A series override (width) wins',
            group: 'Graph',
            showIf: (o) => o.style === 'line',
        }),
    connectNulls: z
        .boolean()
        .default(false)
        .meta({
            title: 'Connect gaps',
            description: 'Draw lines across missing points',
            group: 'Graph',
            showIf: (o) => o.style !== 'bars',
        }),
    showValues: z
        .boolean()
        .default(false)
        .meta({ title: 'Show values', description: 'The number at each point', group: 'Graph' }),
    movingAverage: z
        .number()
        .int()
        .min(0)
        .max(100)
        .default(0)
        .meta({
            title: 'Moving average',
            description: 'A smoothed line per series over this many points (7 days = 7); 0 = off',
            group: 'Overlays',
            range: [0, 30],
        }),
    trendLine: z
        .enum(['none', 'linear', 'exponential'])
        .default('none')
        .meta({
            title: 'Trend line',
            description: 'A fitted line per series, carried across the range',
            group: 'Overlays',
            labels: { none: 'Off', linear: 'Linear', exponential: 'Exponential' },
        }),
    confidence: z
        .number()
        .min(0)
        .max(99.9)
        .default(0)
        .meta({
            title: 'Confidence band',
            description: 'A shaded band per series at this level in % (95); 0 = off. Lines only',
            group: 'Overlays',
            range: [0, 99],
        }),
    previous: z
        .enum(['dashed', 'series', 'hidden'])
        .default('dashed')
        .meta({
            title: 'Previous period',
            description:
                "Series a query marks as the previous period (a PostHog insight's compare), drawn over the current period",
            group: 'Graph',
            labels: { dashed: 'Dashed', series: 'Own series', hidden: 'Hidden' },
        }),
    thresholdStyle: z
        .enum(['dashed', 'line', 'area', 'dashed+area', 'line+area'])
        .default('dashed')
        .meta({
            title: 'Thresholds',
            description: 'How the thresholds (Field tab) draw',
            group: 'Graph',
            labels: {
                dashed: 'Dashed lines',
                line: 'Lines',
                area: 'Areas',
                'dashed+area': 'Dashed + areas',
                'line+area': 'Lines + areas',
            },
        }),
    scale: z
        .enum(['linear', 'log'])
        .default('linear')
        .meta({ title: 'Scale', group: 'Axis', labels: { log: 'Log' } }),
    axisLabel: z.string().optional().meta({ title: 'Left axis label', group: 'Axis' }),
    axisLabelRight: z.string().optional().meta({
        title: 'Right axis label',
        description: 'For series moved to the right axis (Field → per series)',
        group: 'Axis',
    }),
    legend: legendOpt('bottom'),
    legendCalcs: z
        .preprocess(
            (v) => (Array.isArray(v) ? v.filter((c) => (CALCS as readonly string[]).includes(c)) : v),
            z.array(z.enum(CALCS))
        )
        .optional()
        .meta({
            title: 'Values',
            description: 'Show these per series: the legend becomes a table',
            group: 'Legend',
            showIf: (o) => o.legend !== 'none',
        }),
    legendSort: z
        .string()
        .optional()
        .meta({
            title: 'Sort by',
            description: '"name" or one of the values',
            group: 'Legend',
            showIf: (o) => o.legend !== 'none' && !!o.legendCalcs?.length,
        }),
    legendSortDesc: z
        .boolean()
        .optional()
        .meta({
            title: 'Sort descending',
            group: 'Legend',
            showIf: (o) => o.legend !== 'none' && !!o.legendSort,
        }),
    tooltip: z
        .enum(['all', 'single', 'none'])
        .default('all')
        .meta({
            title: 'Tooltip',
            group: 'Tooltip',
            labels: { all: 'All series', single: 'Nearest series', none: 'Hidden' },
        }),
    tooltipSort: z
        .enum(['desc', 'asc', 'none'])
        .default('desc')
        .meta({
            title: 'Order',
            group: 'Tooltip',
            labels: { desc: 'Largest first', asc: 'Smallest first', none: 'Series order' },
            showIf: (o) => o.tooltip !== 'none',
        }),
})
export type TimeseriesOptions = z.output<typeof timeseries>

export const bar = z.object({
    funnel: z
        .boolean()
        .default(false)
        .meta({
            title: 'Funnel',
            description:
                "The categories are steps: each bar is its share of the first, with each step's conversion and drop-off",
            group: 'Bars',
            showIf: (o) => !o.stack,
        }),
    stepReference: z
        .enum(['first', 'previous'])
        .default('first')
        .meta({
            title: 'Conversion from',
            description: 'Each step as a share of the first step, or of the step before it',
            group: 'Bars',
            labels: { first: 'First step', previous: 'Previous step' },
            showIf: (o) => o.funnel,
        }),
    horizontal: z.boolean().default(false).meta({ title: 'Horizontal', group: 'Bars' }),
    stack: z.boolean().default(false).meta({ title: 'Stack series', group: 'Bars' }),
    barStyle: z.enum(['flat', 'gradient', 'gloss']).default('flat').meta({ title: 'Bar style', group: 'Bars' }),
    colorBars: z.boolean().default(false).meta({
        title: 'Colour each bar',
        description: 'One series only: a palette colour per category, as PostHog draws breakdowns',
        group: 'Bars',
    }),
    showValues: z
        .boolean()
        .default(false)
        .meta({ title: 'Show values', description: 'The number at the end of each bar', group: 'Bars' }),
    sort: z
        .enum(['query', 'label', 'value'])
        .default('query')
        .meta({
            title: 'Order',
            description: 'Categories as queried, by name (numbers in order), or largest first',
            group: 'Bars',
            labels: { query: 'As queried', label: 'By name', value: 'Largest first' },
        }),
    axisLabel: z.string().optional().meta({ title: 'Value axis label', group: 'Axis' }),
    legend: legendOpt('bottom'),
})
export type BarOptions = z.output<typeof bar>

export const pie = z.object({
    donut: z.boolean().default(true).meta({ title: 'Donut', group: 'Pie' }),
    showPercent: z.boolean().default(true).meta({ title: 'Show percentages', group: 'Pie' }),
    legend: legendOpt('right'),
})
export type PieOptions = z.output<typeof pie>

export const stat = z.object({
    reduce: reduceOpt,
    field: z.string().optional().meta({
        title: 'Field',
        description:
            'The number column to show (its name), so several stats can share one query; unset shows every number column',
        group: 'Value',
    }),
    textMode: z
        .enum(['auto', 'value', 'value_and_name', 'name'])
        .default('auto')
        .meta({ title: 'Show', group: 'Value', labels: { value_and_name: 'Value + name' } }),
    valueSize: z
        .number()
        .positive()
        .optional()
        .meta({
            title: 'Max value size',
            description: 'px; unset fills the panel',
            group: 'Value',
            range: [12, 160],
        }),
    orientation: z
        .enum(['auto', 'horizontal', 'vertical'])
        .default('auto')
        .meta({
            title: 'Several values',
            description: 'How a stat with several series lays them out',
            group: 'Value',
            labels: { horizontal: 'Rows', vertical: 'Columns' },
        }),
    colorMode: z
        .enum(['value', 'background', 'background_solid', 'none'])
        .default('value')
        .meta({
            title: 'Colour',
            description: 'From the thresholds (Field tab)',
            group: 'Style',
            labels: { value: 'Text', background: 'Gradient', background_solid: 'Solid', none: 'None' },
        }),
    sparkline: z
        .boolean()
        .default(true)
        .meta({ title: 'Sparkline', description: 'The series behind the value', group: 'Style' }),
    sparklineFill: z
        .boolean()
        .default(true)
        .meta({ title: 'Fill sparkline', group: 'Style', showIf: (o) => o.sparkline }),
    showChange: z
        .boolean()
        .default(false)
        .meta({
            title: 'Show change',
            description: 'From the first point to the value',
            group: 'Style',
            showIf: (o) => o.sparkline,
        }),
    compareTo: z.string().optional().meta({
        title: 'Compare with query',
        description:
            "A query (its letter) for the previous period, e.g. with offset $__range: shows the change from it. Series a query marks as the previous period (a PostHog insight's compare) show their change without this",
        group: 'Value',
    }),
    change: z
        .enum(['line', 'badge'])
        .default('badge')
        .meta({
            title: 'Change',
            description:
                "How a stat compared with an earlier period shows the change: a line under the number, or a badge in the corner coloured by whether it's good, with the earlier value under the number",
            group: 'Style',
            labels: { line: 'Line', badge: 'Badge' },
            showIf: (o) => !o.sparkline,
        }),
    goodDirection: z
        .enum(['up', 'down'])
        .default('up')
        .meta({
            title: 'Good change',
            group: 'Style',
            labels: { up: 'Up', down: 'Down' },
            showIf: (o) => o.change === 'badge' || (o.sparkline && (o.showChange || !!o.compareTo)),
        }),
})
export type StatOptions = z.output<typeof stat>

export const gauge = z.object({
    reduce: reduceOpt,
    shape: z
        .enum(['arc', 'bars'])
        .default('bars')
        .meta({
            title: 'Shape',
            description: "Grafana's gauge and bar gauge",
            group: 'Gauge',
            labels: { arc: 'Radial', bars: 'Bars' },
        }),
    orientation: z
        .enum(['horizontal', 'vertical'])
        .default('horizontal')
        .meta({
            title: 'Bars',
            group: 'Gauge',
            labels: { horizontal: 'Horizontal', vertical: 'Vertical' },
            showIf: (o) => o.shape !== 'arc',
        }),
    showName: z.boolean().default(true).meta({ title: 'Show names', group: 'Gauge' }),
})
export type GaugeOptions = z.output<typeof gauge>

export const table = z.object({
    showHeader: z.boolean().default(true).meta({ title: 'Header', group: 'Table' }),
    footer: z
        .enum(REDUCERS)
        .optional()
        .meta({ title: 'Totals row', description: 'A footer row per column', group: 'Table' }),
    pageSize: z.number().int().min(5).max(500).default(50).meta({ title: 'Rows per page', group: 'Table' }),
    expandable: z.boolean().default(false).meta({
        title: 'Expandable rows',
        description: 'Click a row to see all its fields, hidden columns too',
        group: 'Table',
    }),
})
export type TableOptions = z.output<typeof table>

export const retention = z.object({
    display: z
        .enum(['table', 'curve'])
        .default('table')
        .meta({
            title: 'Show as',
            description: 'The cohort table, or a line per cohort over the periods',
            group: 'Retention',
            labels: { table: 'Table', curve: 'Curves' },
        }),
    mean: z.boolean().default(true).meta({
        title: 'Mean',
        description: 'Each period averaged over the cohorts (a row, or the bold line)',
        group: 'Retention',
    }),
    meanBy: z
        .enum(['simple', 'weighted'])
        .default('simple')
        .meta({
            title: 'Mean of',
            description: 'Every cohort counts the same, or by its size',
            group: 'Retention',
            labels: { simple: 'Cohorts', weighted: 'Users (weighted)' },
            showIf: (o) => o.mean,
        }),
    showSize: z
        .boolean()
        .default(true)
        .meta({ title: 'Cohort sizes', description: 'Beside each cohort', group: 'Retention' }),
    incomplete: z.boolean().default(true).meta({
        title: 'Latest period in progress',
        description: "Each cohort's last period drawn dashed",
        group: 'Retention',
    }),
})
export type RetentionOptions = z.output<typeof retention>

export const boxplot = z.object({
    horizontal: z
        .boolean()
        .default(false)
        .meta({ title: 'Horizontal', description: 'Categories down the side', group: 'Box plot' }),
    legend: legendOpt('bottom'),
})
export type BoxPlotOptions = z.output<typeof boxplot>

export const sankey = z.object({
    showValues: z
        .boolean()
        .default(false)
        .meta({ title: 'Show values', description: "Each node's total beside its name", group: 'Flows' }),
    align: z
        .enum(['justify', 'left'])
        .default('justify')
        .meta({
            title: 'Flows that end early',
            description: 'Their last node at the right edge, or in its own column',
            group: 'Flows',
            labels: { justify: 'Right edge', left: 'Own column' },
        }),
})
export type SankeyOptions = z.output<typeof sankey>

export const geomap = z.object({
    colorScale: z
        .enum(['linear', 'log'])
        .default('linear')
        .meta({
            title: 'Colour scale',
            description: 'Log tells small countries apart when one dominates',
            group: 'Map',
            labels: { log: 'Log' },
        }),
    legend: z
        .boolean()
        .default(true)
        .meta({ title: 'Legend', description: 'The colour scale under the map', group: 'Map' }),
})
export type GeomapOptions = z.output<typeof geomap>

export const flamegraph = z.object({
    separator: z.string().default(';').meta({
        title: 'Stack separator',
        description: 'With one text column of stacks (main;handler;query). Several text columns are levels instead',
        group: 'Flame graph',
    }),
    search: z.string().optional().meta({
        title: 'Highlight',
        description: 'Blocks whose name contains this; the rest dim',
        group: 'Flame graph',
    }),
    diffThreshold: z.number().min(0).max(100).optional().meta({
        title: 'Change that counts (%)',
        description: 'With Compare: blocks that moved less read as similar (default 10)',
        group: 'Flame graph',
    }),
})
export type FlameGraphOptions = z.output<typeof flamegraph>

export const heatmap = z.object({
    colorScale: z
        .enum(['log', 'linear'])
        .default('log')
        .meta({ title: 'Colour scale', group: 'Heatmap', labels: { log: 'Log' } }),
    showValues: z.boolean().default(false).meta({
        title: 'Show values',
        description: 'The number in each cell (when it fits)',
        group: 'Heatmap',
    }),
})
export type HeatmapOptions = z.output<typeof heatmap>

export const logs = z.object({
    histogram: z.boolean().default(true).meta({ title: 'Volume histogram', group: 'Logs' }),
    wrap: z.boolean().default(false).meta({ title: 'Wrap lines', group: 'Logs' }),
    fontSize: z.enum(['small', 'medium', 'large']).default('small').meta({ title: 'Text size', group: 'Logs' }),
    columns: z.array(z.string()).optional().meta({
        title: 'Columns',
        description: 'Attributes shown beside each line, e.g. k8s.pod.name (or "add as column" on a line)',
        group: 'Logs',
    }),
    prettify: z.boolean().default(false).meta({ title: 'Pretty-print JSON lines', group: 'Logs' }),
})
export type LogsOptions = z.output<typeof logs>

export const traces = z.object({
    histogram: z.boolean().default(true).meta({ title: 'Volume histogram', group: 'Traces' }),
})
export type TracesOptions = z.output<typeof traces>

export const dashlist = z.object({
    recent: z.boolean().default(true).meta({
        title: 'Recently viewed',
        description: 'The ones opened lately in this browser',
        group: 'Dashboards',
    }),
    search: z
        .boolean()
        .default(false)
        .meta({ title: 'Search', description: 'Dashboards matching all of the below', group: 'Dashboards' }),
    query: z
        .string()
        .optional()
        .meta({ title: 'Title contains', group: 'Dashboards', showIf: (o) => o.search }),
    tags: z
        .string()
        .optional()
        .meta({
            title: 'Tags',
            description: 'Comma-separated; a dashboard needs all of them',
            group: 'Dashboards',
            showIf: (o) => o.search,
        }),
    folder: z
        .string()
        .optional()
        .meta({
            title: 'Folder',
            description: 'And its subfolders, e.g. Infrastructure/Kafka',
            group: 'Dashboards',
            showIf: (o) => o.search,
        }),
    limit: z
        .number()
        .int()
        .min(1)
        .max(200)
        .default(10)
        .meta({ title: 'At most', description: 'Per list', group: 'Dashboards' }),
    showFolder: z.boolean().default(false).meta({ title: 'Show folders', group: 'Dashboards' }),
})
export type DashListOptions = z.output<typeof dashlist>

export const text = z.object({ markdown: z.string().default('').meta({ title: 'Markdown', group: 'Text' }) })
export type TextOptions = z.output<typeof text>
