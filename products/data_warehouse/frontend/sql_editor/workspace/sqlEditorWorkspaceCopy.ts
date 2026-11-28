import type { SqlEditorInspectorTab } from './sqlEditorLayout'

/** The side panel's tab names, shared by the tabs themselves and the layout menu that shows or hides them. */
export const INSPECTOR_TAB_LABELS: Record<SqlEditorInspectorTab, string> = {
    schema: 'Schema',
    variables: 'Variables',
    history: 'History',
}
