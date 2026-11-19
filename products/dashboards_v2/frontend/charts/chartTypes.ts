export interface ChartType {
    type: string
    label: string
    description: string
    needsData: boolean
}

export const CHART_TYPES: ChartType[] = [
    {
        type: 'timeseries',
        label: 'Time series',
        description: 'Values over time as lines, areas or bars',
        needsData: true,
    },
    { type: 'stat', label: 'Number', description: 'One big number, with an optional trend line', needsData: true },
    { type: 'bar', label: 'Bar', description: 'Categories side by side, or the steps of a funnel', needsData: true },
    { type: 'pie', label: 'Pie', description: 'Parts of a whole', needsData: true },
    { type: 'table', label: 'Table', description: 'One row per series, with its value', needsData: true },
    { type: 'gauge', label: 'Gauge', description: 'A value against its minimum and maximum', needsData: true },
    { type: 'heatmap', label: 'Heatmap', description: 'How a distribution changes over time', needsData: true },
    {
        type: 'retention',
        label: 'Retention',
        description: 'How many people come back, period by period',
        needsData: true,
    },
    { type: 'sankey', label: 'Flows', description: 'Paths between steps as ribbons', needsData: true },
    { type: 'boxplot', label: 'Box plot', description: 'The spread of values per day', needsData: true },
    {
        type: 'flamegraph',
        label: 'Flame graph',
        description: 'Where time or cost goes, as nested blocks',
        needsData: true,
    },
    { type: 'logs', label: 'Logs', description: 'Log lines with a volume chart', needsData: true },
    { type: 'traces', label: 'Traces', description: 'Traces and spans with a volume chart', needsData: true },
    { type: 'text', label: 'Text', description: 'Notes, headings and links', needsData: false },
]

export const chartType = (type: string | undefined): ChartType | undefined =>
    CHART_TYPES.find((candidate) => candidate.type === type)

export const CHART_UNITS: [string, string][] = [
    ['', 'None'],
    ['%', 'Percent (0 to 100)'],
    ['1', 'Ratio (0 to 1, shown as a percent)'],
    ['ms', 'Milliseconds'],
    ['s', 'Seconds'],
    ['By', 'Bytes'],
    ['1/s', 'Per second'],
]

export const THRESHOLD_COLORS: [string, string][] = [
    ['green', 'Green'],
    ['yellow', 'Yellow'],
    ['orange', 'Orange'],
    ['red', 'Red'],
    ['blue', 'Blue'],
    ['purple', 'Purple'],
]
