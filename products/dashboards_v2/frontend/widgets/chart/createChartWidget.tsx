import type { ContentWidget } from '../../dashboard/dashboardTypes'
import type { TileAction } from '../../tiles/tileAction'
import { type WidgetDefinition, type WidgetMenuContext, defineWidget } from '../widgetDefinition'
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
 * - `menuActions` adds the host's own entries to every chart's menu, such as "Open in traces".
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
    menuActions?: (context: WidgetMenuContext<ChartConfig>) => TileAction[]
} = {}): WidgetDefinition {
    const vizTypes = withExtraVizTypes(extraVizTypes, states)
    function Chart({ widget }: { widget: ContentWidget<ChartConfig> }): JSX.Element {
        return <ChartWidget widget={widget} vizTypes={vizTypes} runQuery={runQuery} states={states} />
    }
    return defineWidget({
        ...chartSpec(vizTypes),
        Component: Chart,
        menuActions: (context) => [...chartMenuActions(vizTypes, context), ...(menuActions?.(context) ?? [])],
    })
}
