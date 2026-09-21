import posthog from 'posthog-js'

import { type BIConfig, type BIEditorState, BIEditorView } from './biEditorTypes'

export const BI_EDITOR_EVENTS = {
    MODE_SELECTED: 'sql-editor-bi-mode-selected',
    QUERY_RUN: 'sql-editor-bi-query-run',
    QUERY_SAVED: 'sql-editor-bi-query-saved',
} as const

export type BIEditorSaveType = 'endpoint' | 'insight' | 'metric' | 'view'
export type BIEditorSaveOperation = 'create' | 'update'

function uniqueSorted<T extends string>(values: T[]): T[] {
    return [...new Set(values)].sort()
}

function getBIEditorConfigProperties(config: BIConfig): Record<string, unknown> {
    const fields = [
        ...config.rows,
        ...config.columns,
        ...config.values.map((value) => value.field),
        ...config.filters.map((filter) => filter.field),
    ]
    const customExpressionCount =
        [...config.rows, ...config.columns].filter((field) => !field.name).length +
        config.values.filter((value) => value.aggregation === 'custom').length +
        config.filters.filter((filter) => filter.operator === 'custom').length

    return {
        source_kind: config.source ? (config.source.connectionId ? 'external_connection' : 'project_data') : 'none',
        chart_type: config.chartType,
        row_count: config.rows.length,
        column_count: config.columns.length,
        value_count: config.values.length,
        filter_count: config.filters.length,
        field_types: uniqueSorted(fields.map((field) => field.type)),
        aggregation_types: uniqueSorted(config.values.map((value) => value.aggregation)),
        filter_operator_types: uniqueSorted(config.filters.map((filter) => filter.operator)),
        date_bucket_types: uniqueSorted(
            fields.flatMap((field) => (field.dateBucket === undefined ? [] : [field.dateBucket]))
        ),
        custom_expression_count: customExpressionCount,
        sort_kind: config.sort ? 'manual' : 'auto',
        sort_direction: config.sort?.direction ?? null,
    }
}

export function captureBIEditorModeSelected(editorView: BIEditorView, config: BIConfig): void {
    posthog.capture(BI_EDITOR_EVENTS.MODE_SELECTED, {
        mode: editorView,
        ...getBIEditorConfigProperties(config),
    })
}

export function captureBIEditorQueryRun(state: BIEditorState | undefined): void {
    if (state?.editorView !== BIEditorView.BI) {
        return
    }

    posthog.capture(BI_EDITOR_EVENTS.QUERY_RUN, getBIEditorConfigProperties(state.config))
}

export function captureBIEditorQuerySaved(
    state: BIEditorState | undefined,
    saveType: BIEditorSaveType,
    operation: BIEditorSaveOperation,
    addedToDashboard = false
): void {
    if (state?.editorView !== BIEditorView.BI) {
        return
    }

    posthog.capture(BI_EDITOR_EVENTS.QUERY_SAVED, {
        save_type: saveType,
        operation,
        added_to_dashboard: addedToDashboard,
        ...getBIEditorConfigProperties(state.config),
    })
}
