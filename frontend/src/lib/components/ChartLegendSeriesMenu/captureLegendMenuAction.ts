import posthog from 'posthog-js'

interface LegendMenuAction {
    action: string
    /** Which row of the menu was used. */
    source: string
    /** Which chart the legend belongs to, e.g. 'trends' or 'sql'. */
    surface: string
    seriesCount: number
}

/** Reports a chart legend menu action. Shared by the quill legend menu and the legacy insight
 *  legend table so both surfaces land in one event. */
export function captureLegendMenuAction({ action, source, surface, seriesCount }: LegendMenuAction): void {
    // pinned: analytics event and property names — renaming breaks existing insights
    posthog.capture('insight_legend_context_menu', {
        action,
        source,
        surface,
        series_count: seriesCount,
    })
}
