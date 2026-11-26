import type { ContentWidget } from '../../dashboard/document/dashboardTypes'
import type { MenuAction } from '../../menu/menuAction'
import { type WidgetType, type WidgetMenuContext, defineWidget } from '../widgetDefinition'
import { chartMenuActions } from './chartMenuActions'
import { type ChartConfig, chartSpec } from './chartSpec'
import { ChartWidget } from './ChartWidget'
import { BarLoading } from './viz/bar/BarLoading'
import { barSpec } from './viz/bar/barSpec'
import { BarViz } from './viz/bar/BarViz'
import { LineLoading } from './viz/line/LineLoading'
import { lineSpec } from './viz/line/lineSpec'
import { LineViz } from './viz/line/LineViz'
import { StatLoading } from './viz/stat/StatLoading'
import { statSpec } from './viz/stat/statSpec'
import { StatViz } from './viz/stat/StatViz'
import { type ChartStates, type RunQuery, type VizDefinition, defineViz } from './vizTypes'

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
 * - `states` sets the loading, empty and error states for every chart, unless one of the host's own kinds sets its own.
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
        menuActions: (actions, context) => {
            const withChart = [...actions, ...chartMenuActions(vizTypes, context)]
            return menuActions ? menuActions(withChart, context) : withChart
        },
    })
}
