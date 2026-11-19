import type { ComponentType } from 'react'
import type { z } from 'zod'

import type { Panel } from '../spec'
import { BarViz } from './BarViz'
import { BoxPlotViz } from './BoxPlotViz'
import type { DrillContext } from './drilldown'
import { FlameGraphViz } from './FlameGraphViz'
import type { DataFrame } from './frame'
import { GaugeViz } from './GaugeViz'
import { HeatmapViz } from './HeatmapViz'
import { LogsViz } from './LogsViz'
import {
    bar,
    boxplot,
    flamegraph,
    logs,
    gauge,
    heatmap,
    pie,
    retention,
    sankey,
    stat,
    table,
    text,
    timeseries,
    traces,
} from './options'
import { PieViz } from './PieViz'
import { RetentionViz } from './RetentionViz'
import { SankeyViz } from './SankeyViz'
import { StatViz } from './StatViz'
import { TableViz } from './TableViz'
import { TextViz } from './TextViz'
import { TimeseriesViz } from './TimeseriesViz'
import { TracesViz } from './TracesViz'

export interface VizProps<O = Record<string, unknown>> {
    frames: DataFrame[]
    panel: Panel
    options: O
    height: number
    width: number
    range?: { from: number; to: number }
    time?: { from: string; to: string }
    timezone?: string
    onEditPanel?: (edit: (panel: Panel) => Panel) => void
    onTimeRange?: (from: number, to: number) => void
    onDrill?: (context: DrillContext) => void
}

interface VizDef {
    label: string
    options: z.ZodObject<any>
    component: ComponentType<VizProps<any>>
    needsData: boolean
}

export const vizRegistry: Record<string, VizDef> = {
    timeseries: { label: 'Time series', needsData: true, component: TimeseriesViz, options: timeseries },
    bar: { label: 'Bar', needsData: true, component: BarViz, options: bar },
    pie: { label: 'Pie', needsData: true, component: PieViz, options: pie },
    stat: { label: 'Stat', needsData: true, component: StatViz, options: stat },
    table: { label: 'Table', needsData: true, component: TableViz, options: table },
    gauge: { label: 'Gauge', needsData: true, component: GaugeViz, options: gauge },
    heatmap: { label: 'Heatmap', needsData: true, component: HeatmapViz, options: heatmap },
    retention: { label: 'Retention', needsData: true, component: RetentionViz, options: retention },
    boxplot: { label: 'Box plot', needsData: true, component: BoxPlotViz, options: boxplot },
    sankey: { label: 'Flows', needsData: true, component: SankeyViz, options: sankey },
    flamegraph: { label: 'Flame graph', needsData: true, component: FlameGraphViz, options: flamegraph },
    logs: { label: 'Logs', needsData: true, component: LogsViz, options: logs },
    traces: { label: 'Traces', needsData: true, component: TracesViz, options: traces },
    text: { label: 'Text', needsData: false, component: TextViz, options: text },
}

export function parseOptions(def: VizDef, raw: unknown): { options: Record<string, unknown>; error?: string } {
    const result = def.options.safeParse(raw ?? {})
    if (result.success) {
        return { options: result.data }
    }
    return {
        options: def.options.parse({}),
        error: result.error.issues.map((issue) => `${issue.path.join('.')}: ${issue.message}`).join('; '),
    }
}
