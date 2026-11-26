import { lazyWithRetry } from 'lib/utils/retryImport'

import type { ContentWidget } from '../../dashboard/document/dashboardTypes'
import type { MenuAction } from '../../menu/menuAction'
import type { RunQuery } from '../../query/queryTypes'
import { type WidgetType, type WidgetMenuContext, defineWidget } from '../core/widgetDefinition'
import { WidgetLoading } from '../core/WidgetView'
import { chartMenuActions } from './chartMenuActions'
import { ChartSampleData } from './ChartSampleData'
import { type ChartConfig, chartSpec } from './chartSpec'
import { ChartWidget } from './ChartWidget'
import { BarLoading } from './viz/bar/BarLoading'
import { barSpec } from './viz/bar/barSpec'
import { LineLoading } from './viz/line/LineLoading'
import { lineSpec } from './viz/line/lineSpec'
import { StatLoading } from './viz/stat/StatLoading'
import { statSpec } from './viz/stat/statSpec'
import { type ChartStates, type VizDefinition, defineViz } from './vizTypes'

// Each kind of chart loads its drawing code the first time a tile draws it, so a page fetches only the kinds it shows.
const StatViz = lazyWithRetry(() => import('./viz/stat/StatViz').then((module) => ({ default: module.StatViz })))
const LineViz = lazyWithRetry(() => import('./viz/line/LineViz').then((module) => ({ default: module.LineViz })))
const BarViz = lazyWithRetry(() => import('./viz/bar/BarViz').then((module) => ({ default: module.BarViz })))

/** The kinds of chart that ship with dashboards v2, in add menu order. Every chart widget can draw them. */
export const DEFAULT_VIZ_TYPES: VizDefinition[] = [
    defineViz({ ...statSpec, Component: StatViz, Loading: StatLoading }),
    defineViz({ ...lineSpec, Component: LineViz, Loading: LineLoading }),
    defineViz({ ...barSpec, Component: BarViz, Loading: BarLoading }),
]

// A host's `states` replace the built-in kinds' own states, but not those of the host's own kinds.
function withExtraVizTypes(extra: VizDefinition[], states: ChartStates | undefined): VizDefinition[] {
    const builtIn = DEFAULT_VIZ_TYPES.map(
        (viz) => extra.find((candidate) => candidate.type === viz.type) ?? (states ? { ...viz, ...states } : viz)
    )
    return [...builtIn, ...extra.filter((viz) => !DEFAULT_VIZ_TYPES.some((known) => known.type === viz.type))]
}

/**
 * The chart widget type. It can draw every built-in kind of chart, so a dashboard saved by another host still renders.
 * - `extraVizTypes` adds a host's own kinds of chart, or replaces a built-in kind of the same type.
 * - `runQuery` runs each chart's query. The host supplies it, so the dashboard never fetches data itself.
 * - `states` sets the loading, empty, error and sample data states for every chart, unless one of the host's own kinds sets its own.
 * - `menuActions` gets every chart's menu, with the chart's own entries added, so the host can add entries such as
 *   "Open in traces" or remove ones it does not want.
 */
export function createChartWidget({
    extraVizTypes = [],
    runQuery,
    states,
    menuActions,
}: {
    extraVizTypes?: VizDefinition[]
    runQuery?: RunQuery
    states?: ChartStates
    menuActions?: (actions: MenuAction[], context: WidgetMenuContext<ChartConfig>) => MenuAction[]
} = {}): WidgetType {
    const vizTypes = withExtraVizTypes(extraVizTypes, states)
    function Chart({ widget }: { widget: ContentWidget<ChartConfig> }): JSX.Element {
        return <ChartWidget widget={widget} vizTypes={vizTypes} runQuery={runQuery} states={states} />
    }
    // Shaped like the chart's own kind, so a tile waiting to mount or load already looks like its chart.
    function ChartLoading({ widget }: { widget: ContentWidget<ChartConfig> }): JSX.Element {
        const viz = vizTypes.find((candidate) => candidate.type === widget.config.viz.type)
        const options = viz?.optionsSchema.safeParse(widget.config.viz.options ?? {})
        const Loading = viz?.Loading ?? states?.Loading
        return Loading && options?.success ? <Loading options={options.data} /> : <WidgetLoading />
    }
    function ChartSample({ widget }: { widget: ContentWidget<ChartConfig> }): JSX.Element | null {
        const viz = vizTypes.find((candidate) => candidate.type === widget.config.viz.type)
        const options = viz?.optionsSchema.safeParse(widget.config.viz.options ?? {})
        if (!viz || !options?.success) {
            return null
        }
        const SampleData = viz.SampleData ?? states?.SampleData
        if (SampleData) {
            return <SampleData options={options.data} />
        }
        const Loading = viz.Loading ?? states?.Loading ?? WidgetLoading
        return <ChartSampleData viz={viz} options={options.data} Loading={Loading} />
    }
    const firstType = vizTypes.find((viz) => viz.type === 'line')?.type ?? vizTypes[0]?.type ?? 'line'
    return defineWidget<ChartConfig, 'chart'>({
        ...chartSpec(vizTypes),
        addTileOptions: [
            {
                label: 'Chart',
                // TODO(2026-11-23): Replace this hardcoded query with one the person picks when they add the tile.
                // The query is temporary. It gives the add menu a widget to insert before a query picker exists.
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
        SampleData: ChartSample,
        menuActions: (actions, context) => {
            const withChart = [...actions, ...chartMenuActions(vizTypes, context)]
            return menuActions ? menuActions(withChart, context) : withChart
        },
    })
}
