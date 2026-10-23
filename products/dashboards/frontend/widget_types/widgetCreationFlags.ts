import widgetFormFields from '../generated/widget-form-fields.json'

const WIDGET_MANIFEST = widgetFormFields.widgets as Record<string, { creationFlag?: string | null }>

/** The feature flag a user needs to add this widget type, or null. SSOT is `WidgetSpec.creation_flag` on the
 * backend, flowed through `hogli build:widget-types`. */
export function getDashboardWidgetCreationFlag(widgetType: string): string | null {
    return WIDGET_MANIFEST[widgetType]?.creationFlag ?? null
}
