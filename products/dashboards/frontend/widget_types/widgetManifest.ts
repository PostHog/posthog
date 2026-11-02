import widgetFormFields from '../generated/widget-form-fields.json'

const WIDGET_MANIFEST = widgetFormFields.widgets as Record<
    string,
    { creationFlag?: string | null; dashboardFilterKeys?: string[] }
>

/** The feature flag a user needs to add this widget type, or null. SSOT is `WidgetSpec.creation_flag` on the
 * backend, flowed through `hogli build:widget-types`. */
export function getDashboardWidgetCreationFlag(widgetType: string): string | null {
    return WIDGET_MANIFEST[widgetType]?.creationFlag ?? null
}

/** The dashboard filter keys this widget type follows, empty when it ignores dashboard filters. SSOT is
 * `WidgetSpec.dashboard_filter_keys` on the backend, flowed through `hogli build:widget-types`. */
export function getDashboardWidgetFilterKeys(widgetType: string): readonly string[] {
    return WIDGET_MANIFEST[widgetType]?.dashboardFilterKeys ?? []
}
