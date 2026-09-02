import widgetFormFields from '../../generated/widget-form-fields.json'

const WIDGET_MANIFEST = widgetFormFields.widgets as Record<string, { live?: boolean }>

/** SSOT is `WidgetSpec.is_live` on the backend, flowed through `hogli build:widget-types`. */
export function isLiveDashboardWidgetType(widgetType: string): boolean {
    return WIDGET_MANIFEST[widgetType]?.live === true
}

/**
 * Contract for the run_widgets result of a live widget (`WidgetSpec.is_live` on the backend).
 *
 * The result is a one-shot SEED of the widget's real-time state, not the state itself: the tile
 * self-updates client-side afterwards. `generatedAt` is the server clock at seed-query time —
 * streamed events at or before it are already counted in the seed, so client merges use it to
 * avoid double counting. Any re-run of run_widgets (manual tile refresh, dashboard auto-refresh)
 * re-seeds, so seed merges must be idempotent.
 */
export interface LiveWidgetSeedPayload {
    /** Server clock at seed-query time (ISO-8601). */
    generatedAt: string
}
