import widgetFormFields from '../../generated/widget-form-fields.json'

const WIDGET_MANIFEST = widgetFormFields.widgets as Record<string, { live?: boolean }>

/** SSOT is `WidgetSpec.is_live` on the backend, flowed through `hogli build:widget-types`. */
export function isLiveDashboardWidgetType(widgetType: string): boolean {
    return WIDGET_MANIFEST[widgetType]?.live === true
}
