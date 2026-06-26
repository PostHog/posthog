import { InsightsThresholdBounds } from '~/queries/schema/schema-general'

import { hasThresholdBounds, valueBreachesBounds } from './alertPreviewShared'
import { AlertConfig, isHogQLAlertConfig } from './types'

/** Mirror of the backend's ANY_ROW_MAX_ROWS (products/alerts/backend/evaluation/hogql.py) — keep
 * the two in sync. Advisory only; the backend extractor is the evaluation-time authority. */
export const HOGQL_ANY_ROW_MAX_ROWS = 50

/** Mirror of the backend's LAST_ROW_MAX_ROWS (= MAX_SELECT_RETURNED_ROWS). In last_row mode the
 * backend rejects a result this large because the tail may be truncated, so the last row may not be
 * the true last row. first_row is immune — it reads the head. */
export const HOGQL_LAST_ROW_MAX_ROWS = 50000

/** One result row as the alert would read it, for the configure-time preview table. */
export interface HogQLAlertPreviewRow {
    /** Label-column value, falling back to the row number — mirrors the backend's row labeling. */
    label: string
    value: number | null
    breaching: boolean
}

/** What a SQL alert would evaluate right now, mirroring the backend extractor's column
 * resolution and shape checks so problems surface at configure time, not at the first check.
 * This is the advisory half of the PREVIEW MIRROR CONTRACT — the rule inventory lives on
 * `HogQLExtractor` in products/alerts/backend/evaluation/hogql.py; any rule change there must
 * land here and in both test suites. */
export type HogQLAlertPreview =
    | { status: 'no-rows' }
    | { status: 'bad-shape' }
    | { status: 'too-many-rows'; rowCount: number }
    | { status: 'last-row-truncated'; rowCount: number }
    | { status: 'ambiguous-columns'; columnNames: string[] | null }
    | { status: 'missing-column'; column: string; columnNames: string[] | null }
    | { status: 'not-numeric'; value: string }
    | {
          status: 'ok'
          mode: 'last_row' | 'first_row' | 'any_row'
          /** Resolved evaluated column name; null when the result has no column metadata. */
          columnName: string | null
          /** Resolved label column name; null when rows are labeled by row number. */
          labelColumnName: string | null
          currentValue: number
          previousValue: number | null
          rowCount: number
          /** Rows whose value breaches the current absolute bounds; null when not computable. */
          breachingRows: number | null
          rows: HogQLAlertPreviewRow[]
      }

const _cellValue = (row: unknown, index: number): number | null => {
    if (!Array.isArray(row) || index >= row.length) {
        return null
    }
    const cell = row[index]
    if (cell === null) {
        return 0 // None buckets evaluate as 0, matching the backend
    }
    return typeof cell === 'number' && Number.isFinite(cell) ? cell : null
}

/** Mirror of the backend's `_column_is_numeric` (products/alerts/backend/evaluation/hogql.py): a
 * column is numeric by its most recent non-null value. Advisory only — the backend owns
 * authoritative resolution, so drift just yields a wrong picker suggestion, not a wrong evaluation.
 * Caveat: a trailing footer/total row with a string cell will mislabel an otherwise-numeric column. */
export const columnIsNumeric = (rows: unknown[], index: number): boolean => {
    for (let i = rows.length - 1; i >= 0; i--) {
        const row = rows[i]
        if (!Array.isArray(row) || index >= row.length) {
            return false
        }
        const cell = row[index]
        if (cell === null) {
            continue
        }
        return typeof cell === 'number' && Number.isFinite(cell)
    }
    return false
}

export function deriveHogQLAlertPreview(
    insightData: Record<string, any> | null,
    config: AlertConfig | null | undefined,
    bounds: InsightsThresholdBounds | null | undefined
): HogQLAlertPreview | null {
    const rows = insightData?.result
    if (!Array.isArray(rows)) {
        return null // No result loaded yet — fall back to the static hint
    }
    if (rows.length === 0) {
        return { status: 'no-rows' }
    }
    const hogqlConfig = isHogQLAlertConfig(config) ? config : null
    const mode = hogqlConfig?.evaluation ?? 'last_row'
    // first_row reads the head (newest first), last_row/any_row the tail; the anchor row is what
    // last_row/first_row evaluate and what the shape check applies to.
    const anchorRow = mode === 'first_row' ? rows[0] : rows[rows.length - 1]
    if (!Array.isArray(anchorRow)) {
        return { status: 'bad-shape' }
    }
    const lastRow = anchorRow
    if (mode === 'any_row' && rows.length > HOGQL_ANY_ROW_MAX_ROWS) {
        return { status: 'too-many-rows', rowCount: rows.length }
    }
    if (mode === 'last_row' && rows.length >= HOGQL_LAST_ROW_MAX_ROWS) {
        return { status: 'last-row-truncated', rowCount: rows.length }
    }
    const columnNames = Array.isArray(insightData?.columns) ? insightData.columns.map(String) : null

    // Resolve the evaluated column the way the backend does: explicit pick, single column,
    // or the single numeric column — anything else needs the user to choose.
    let valueIndex: number
    if (hogqlConfig?.column != null) {
        const index = columnNames?.indexOf(hogqlConfig.column) ?? -1
        if (index < 0) {
            return { status: 'missing-column', column: hogqlConfig.column, columnNames }
        }
        valueIndex = index
    } else if (lastRow.length === 1) {
        valueIndex = 0
    } else {
        const numericIndexes = Array.from({ length: lastRow.length }, (_, i) => i).filter((i) =>
            columnIsNumeric(rows, i)
        )
        if (numericIndexes.length !== 1) {
            return { status: 'ambiguous-columns', columnNames }
        }
        valueIndex = numericIndexes[0]
    }

    const currentValue = _cellValue(lastRow, valueIndex)
    if (currentValue === null) {
        return { status: 'not-numeric', value: String(lastRow[valueIndex]) }
    }

    // Label column: explicit pick, else the first non-evaluated column (e.g. the GROUP BY key).
    let labelIndex: number | null = null
    if (hogqlConfig?.label_column != null) {
        const index = columnNames?.indexOf(hogqlConfig.label_column) ?? -1
        if (index < 0) {
            return { status: 'missing-column', column: hogqlConfig.label_column, columnNames }
        }
        labelIndex = index
    } else if (lastRow.length > 1) {
        labelIndex = Array.from({ length: lastRow.length }, (_, i) => i).find((i) => i !== valueIndex) ?? null
    }

    // Per-row view (and backtest): with absolute bounds, mark which rows would breach right now.
    const bounded = hasThresholdBounds(bounds)
    const previewRows: HogQLAlertPreviewRow[] = rows.map((row, i) => {
        const value = _cellValue(row, valueIndex)
        const labelCell = labelIndex !== null && Array.isArray(row) && labelIndex < row.length ? row[labelIndex] : null
        return {
            label: labelCell != null ? String(labelCell) : `row ${i + 1}`,
            value,
            breaching: valueBreachesBounds(value, bounds),
        }
    })

    // Previous row is the second from the anchor end: tail for last_row, head for first_row.
    const previousRow = mode === 'first_row' ? rows[1] : rows[rows.length - 2]
    const previousValue = rows.length > 1 ? _cellValue(previousRow, valueIndex) : null
    return {
        status: 'ok',
        mode,
        columnName: columnNames?.[valueIndex] ?? null,
        labelColumnName: labelIndex !== null ? (columnNames?.[labelIndex] ?? null) : null,
        currentValue,
        previousValue,
        rowCount: rows.length,
        breachingRows: bounded ? previewRows.filter((row) => row.breaching).length : null,
        rows: previewRows,
    }
}
