import { lazyWithRetry } from 'lib/utils/retryImport'

import type { MenuAction } from '../../menu/menuAction'
import type { RunQuery } from '../../query/queryTypes'
import { type PanelType, type PanelMenuContext, definePanel } from '../core/panelDefinition'
import { type ContentPanel } from '../core/panelSchema'
import { PanelLoading } from '../core/PanelView'
import { chartMenuActions } from './chartMenuActions'
import { ChartPanel } from './ChartPanel'
import { ChartSampleData } from './ChartSampleData'
import { type ChartConfig, chartSpec } from './chartSpec'
import { AreaLoading } from './viz/area/AreaLoading'
import { areaSpec } from './viz/area/areaSpec'
import { BarLoading } from './viz/bar/BarLoading'
import { barSpec } from './viz/bar/barSpec'
import { BarListLoading } from './viz/barList/BarListLoading'
import { barListSpec } from './viz/barList/barListSpec'
import { BoxPlotLoading } from './viz/boxPlot/BoxPlotLoading'
import { boxPlotSpec } from './viz/boxPlot/boxPlotSpec'
import { comboSpec } from './viz/combo/comboSpec'
import { FlameGraphLoading } from './viz/flameGraph/FlameGraphLoading'
import { flameGraphSpec } from './viz/flameGraph/flameGraphSpec'
import { FunnelLoading } from './viz/funnel/FunnelLoading'
import { funnelSpec } from './viz/funnel/funnelSpec'
import { GaugeLoading } from './viz/gauge/GaugeLoading'
import { gaugeSpec } from './viz/gauge/gaugeSpec'
import { HeatmapLoading } from './viz/heatmap/HeatmapLoading'
import { heatmapSpec } from './viz/heatmap/heatmapSpec'
import { LineLoading } from './viz/line/LineLoading'
import { lineSpec } from './viz/line/lineSpec'
import { MetricLoading } from './viz/metric/MetricLoading'
import { metricSpec } from './viz/metric/metricSpec'
import { PieLoading } from './viz/pie/PieLoading'
import { pieSpec } from './viz/pie/pieSpec'
import { ProportionLoading } from './viz/proportion/ProportionLoading'
import { proportionSpec } from './viz/proportion/proportionSpec'
import { SankeyLoading } from './viz/sankey/SankeyLoading'
import { sankeySpec } from './viz/sankey/sankeySpec'
import { ScatterLoading } from './viz/scatter/ScatterLoading'
import { scatterSpec } from './viz/scatter/scatterSpec'
import { SlopeLoading } from './viz/slope/SlopeLoading'
import { slopeSpec } from './viz/slope/slopeSpec'
import { type ChartStates, type VizDefinition, defineViz } from './vizTypes'

// Each kind of chart loads its drawing code the first time a tile draws it, so a page fetches only the kinds it shows.
const MetricViz = lazyWithRetry(() =>
    import('./viz/metric/MetricViz').then((module) => ({ default: module.MetricViz }))
)
const LineViz = lazyWithRetry(() => import('./viz/line/LineViz').then((module) => ({ default: module.LineViz })))
const BarViz = lazyWithRetry(() => import('./viz/bar/BarViz').then((module) => ({ default: module.BarViz })))
const AreaViz = lazyWithRetry(() => import('./viz/area/AreaViz').then((module) => ({ default: module.AreaViz })))
const ComboViz = lazyWithRetry(() => import('./viz/combo/ComboViz').then((module) => ({ default: module.ComboViz })))
const PieViz = lazyWithRetry(() => import('./viz/pie/PieViz').then((module) => ({ default: module.PieViz })))
const BarListViz = lazyWithRetry(() =>
    import('./viz/barList/BarListViz').then((module) => ({ default: module.BarListViz }))
)
const ProportionViz = lazyWithRetry(() =>
    import('./viz/proportion/ProportionViz').then((module) => ({ default: module.ProportionViz }))
)
const FunnelViz = lazyWithRetry(() =>
    import('./viz/funnel/FunnelViz').then((module) => ({ default: module.FunnelViz }))
)
const GaugeViz = lazyWithRetry(() => import('./viz/gauge/GaugeViz').then((module) => ({ default: module.GaugeViz })))
const HeatmapViz = lazyWithRetry(() =>
    import('./viz/heatmap/HeatmapViz').then((module) => ({ default: module.HeatmapViz }))
)
const ScatterViz = lazyWithRetry(() =>
    import('./viz/scatter/ScatterViz').then((module) => ({ default: module.ScatterViz }))
)
const BoxPlotViz = lazyWithRetry(() =>
    import('./viz/boxPlot/BoxPlotViz').then((module) => ({ default: module.BoxPlotViz }))
)
const SlopeViz = lazyWithRetry(() => import('./viz/slope/SlopeViz').then((module) => ({ default: module.SlopeViz })))
const SankeyViz = lazyWithRetry(() =>
    import('./viz/sankey/SankeyViz').then((module) => ({ default: module.SankeyViz }))
)
const FlameGraphViz = lazyWithRetry(() =>
    import('./viz/flameGraph/FlameGraphViz').then((module) => ({ default: module.FlameGraphViz }))
)

/** The kinds of chart that ship with dashboards v2, in add menu order. Every chart panel can draw them. */
export const DEFAULT_VIZ_TYPES: VizDefinition[] = [
    defineViz({ ...metricSpec, Component: MetricViz, Loading: MetricLoading }),
    defineViz({ ...lineSpec, Component: LineViz, Loading: LineLoading }),
    defineViz({ ...barSpec, Component: BarViz, Loading: BarLoading }),
    defineViz({ ...areaSpec, Component: AreaViz, Loading: AreaLoading }),
    defineViz({ ...comboSpec, Component: ComboViz, Loading: BarLoading }),
    defineViz({ ...pieSpec, Component: PieViz, Loading: PieLoading }),
    defineViz({ ...barListSpec, Component: BarListViz, Loading: BarListLoading }),
    defineViz({ ...proportionSpec, Component: ProportionViz, Loading: ProportionLoading }),
    defineViz({ ...funnelSpec, Component: FunnelViz, Loading: FunnelLoading }),
    defineViz({ ...gaugeSpec, Component: GaugeViz, Loading: GaugeLoading }),
    defineViz({ ...heatmapSpec, Component: HeatmapViz, Loading: HeatmapLoading }),
    defineViz({ ...scatterSpec, Component: ScatterViz, Loading: ScatterLoading }),
    defineViz({ ...boxPlotSpec, Component: BoxPlotViz, Loading: BoxPlotLoading }),
    defineViz({ ...slopeSpec, Component: SlopeViz, Loading: SlopeLoading }),
    defineViz({ ...sankeySpec, Component: SankeyViz, Loading: SankeyLoading }),
    defineViz({ ...flameGraphSpec, Component: FlameGraphViz, Loading: FlameGraphLoading }),
]

// A host's `states` replace the built-in kinds' own states, but not those of the host's own kinds.
function withExtraVizTypes(extra: VizDefinition[], states: ChartStates | undefined): VizDefinition[] {
    const builtIn = DEFAULT_VIZ_TYPES.map(
        (viz) => extra.find((candidate) => candidate.type === viz.type) ?? (states ? { ...viz, ...states } : viz)
    )
    return [...builtIn, ...extra.filter((viz) => !DEFAULT_VIZ_TYPES.some((known) => known.type === viz.type))]
}

/**
 * The chart panel type. It can draw every built-in kind of chart, so a dashboard saved by another host still renders.
 * - `extraVizTypes` adds a host's own kinds of chart, or replaces a built-in kind of the same type.
 * - `runQuery` runs each chart's query. The host supplies it, so the dashboard never fetches data itself.
 * - `states` sets the loading, empty, error and sample data states for every chart, unless one of the host's own kinds sets its own.
 * - `sampleData` draws every chart from made-up data and runs no queries, such as in a project with no events yet.
 * - `menuActions` gets every chart's menu, with the chart's own entries added, so the host can add entries such as
 *   "Open in traces" or remove ones it does not want.
 */
export function createChartPanel({
    extraVizTypes = [],
    runQuery,
    states,
    sampleData = false,
    menuActions,
}: {
    extraVizTypes?: VizDefinition[]
    runQuery?: RunQuery
    states?: ChartStates
    sampleData?: boolean
    menuActions?: (actions: MenuAction[], context: PanelMenuContext<ChartConfig>) => MenuAction[]
} = {}): PanelType {
    const vizTypes = withExtraVizTypes(extraVizTypes, states)
    // Shaped like the chart's own kind, so a tile waiting to mount or load already looks like its chart.
    function ChartLoading({ panel }: { panel: ContentPanel<ChartConfig> }): JSX.Element {
        const viz = vizTypes.find((candidate) => candidate.type === panel.config.viz.type)
        const options = viz?.optionsSchema.safeParse(panel.config.viz.options ?? {})
        const Loading = viz?.Loading ?? states?.Loading
        return Loading && options?.success ? <Loading options={options.data} /> : <PanelLoading />
    }
    function ChartSample({ panel }: { panel: ContentPanel<ChartConfig> }): JSX.Element | null {
        const viz = vizTypes.find((candidate) => candidate.type === panel.config.viz.type)
        const options = viz?.optionsSchema.safeParse(panel.config.viz.options ?? {})
        if (!viz || !options?.success) {
            return null
        }
        const SampleData = viz.SampleData ?? states?.SampleData
        if (SampleData) {
            return <SampleData options={options.data} />
        }
        const Loading = viz.Loading ?? states?.Loading ?? PanelLoading
        return <ChartSampleData viz={viz} options={options.data} Loading={Loading} />
    }
    function Chart({ panel }: { panel: ContentPanel<ChartConfig> }): JSX.Element | null {
        if (sampleData) {
            return <ChartSample panel={panel} />
        }
        return <ChartPanel panel={panel} vizTypes={vizTypes} runQuery={runQuery} states={states} />
    }
    const firstType = vizTypes.find((viz) => viz.type === 'line')?.type ?? vizTypes[0]?.type ?? 'line'
    return definePanel<ChartConfig, 'chart'>({
        ...chartSpec(vizTypes),
        addTileOptions: [
            {
                label: 'Chart',
                // TODO(2026-11-23): Replace this hardcoded query with one the person picks when they add the tile.
                // The query is temporary. It gives the add menu a panel to insert before a query picker exists.
                create: () => ({
                    type: 'chart',
                    title: 'New chart',
                    config: {
                        query: { language: 'hogql', query: 'select count() from events' },
                        viz: { type: firstType },
                    },
                }),
            },
        ],
        Component: Chart,
        Loading: ChartLoading,
        menuActions: (actions, context) => {
            const withChart = [...actions, ...chartMenuActions(vizTypes, context)]
            return menuActions ? menuActions(withChart, context) : withChart
        },
    })
}
