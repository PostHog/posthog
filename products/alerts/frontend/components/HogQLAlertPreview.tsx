import type { ReactNode } from 'react'

import { LemonBanner, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { AlertConditionType } from '~/queries/schema/schema-general'

import {
    HOGQL_ANY_ROW_MAX_ROWS,
    HogQLAlertPreview,
    HogQLAlertPreviewRow,
} from 'products/alerts/frontend/logic/hogqlAlertPreview'

const PREVIEW_TABLE_MAX_ROWS = 10

function HogQLPreviewStatus({ wouldFire, children }: { wouldFire: boolean | null; children: ReactNode }): JSX.Element {
    return (
        <div className="rounded border border-border bg-bg-light p-3 text-sm">
            {wouldFire !== null ? (
                <LemonTag type={wouldFire ? 'danger' : 'success'} className="mr-2">
                    {wouldFire ? 'Would fire' : 'Would not fire'}
                </LemonTag>
            ) : null}
            {children}
        </div>
    )
}

/** Per-row view of what the alert would evaluate: breaching rows first (any-row) or the most
 * recent rows (last-row), capped to keep the modal compact. Shown even before a threshold is set.
 * seeing the rows is how users orient on what to alert on; the breach column appears once bounds exist. */
export function HogQLAlertPreviewRowsTable({
    preview,
}: {
    preview: Extract<HogQLAlertPreview, { status: 'ok' }>
}): JSX.Element | null {
    const isAnyRow = preview.mode === 'any_row'
    const isFirstRow = preview.mode === 'first_row'
    const rows = isAnyRow
        ? [...preview.rows].sort((a, b) => Number(b.breaching) - Number(a.breaching)).slice(0, PREVIEW_TABLE_MAX_ROWS)
        : isFirstRow
          ? preview.rows.slice(0, PREVIEW_TABLE_MAX_ROWS) // newest first: the head
          : preview.rows.slice(-PREVIEW_TABLE_MAX_ROWS) // newest last: the tail
    const hiddenCount = preview.rows.length - rows.length
    const showStatus = preview.breachingRows !== null
    // Only the evaluated row is tagged in single-row modes (the banner carries the rest); any-row
    // tags them all. first_row evaluates the top row, last_row the bottom.
    const evaluatedIndex = isAnyRow ? null : isFirstRow ? 0 : rows.length - 1
    // The trimmed rows are always the older ones. In last_row they sit before the visible window
    // (note above), in first_row after it (note below); below would read as newer data otherwise.
    const overflowNote =
        hiddenCount > 0 ? (
            <div className="text-muted text-xs">+{pluralize(hiddenCount, isAnyRow ? 'more row' : 'older row')}</div>
        ) : null

    return (
        <div className="deprecated-space-y-1">
            {!isFirstRow && overflowNote}
            <LemonTable
                size="small"
                dataSource={rows}
                columns={[
                    {
                        title: preview.labelColumnName ?? 'Row',
                        render: (_, row: HogQLAlertPreviewRow) => row.label,
                    },
                    {
                        title: preview.columnName ?? 'Value',
                        render: (_, row: HogQLAlertPreviewRow) =>
                            row.value !== null ? humanFriendlyNumber(row.value) : 'N/A',
                    },
                    ...(showStatus
                        ? [
                              {
                                  title: '',
                                  render: (_: unknown, row: HogQLAlertPreviewRow, index: number) =>
                                      index === evaluatedIndex || isAnyRow ? (
                                          row.breaching ? (
                                              <LemonTag type="danger">Would fire</LemonTag>
                                          ) : (
                                              <LemonTag type="success">Would not fire</LemonTag>
                                          )
                                      ) : null,
                              },
                          ]
                        : []),
                ]}
            />
            {isFirstRow && overflowNote}
        </div>
    )
}

function getHogQLPreviewBannerCopy(preview: Exclude<HogQLAlertPreview, { status: 'ok' }>): ReactNode {
    switch (preview.status) {
        case 'no-rows':
            return 'The query currently returns no rows. The alert evaluates this as 0, so a lower bound can still fire.'
        case 'too-many-rows':
            return (
                <>
                    Any-row alerts evaluate at most {HOGQL_ANY_ROW_MAX_ROWS} rows, but the query returns{' '}
                    {preview.rowCount}. Add a LIMIT or aggregate the query, or the alert will fail to evaluate.
                </>
            )
        case 'last-row-truncated':
            return (
                <>
                    The query returns {preview.rowCount.toLocaleString()} rows and may be truncated, so the last row
                    isn't reliably the newest. Add a LIMIT, aggregate the query, or switch to evaluating the first row
                    (newest-first ordering), or the alert will fail to evaluate.
                </>
            )
        case 'bad-shape':
            return "The query result isn't plain rows of values. The alert requires a query returning rows with a numeric column."
        case 'ambiguous-columns':
            return (
                <>
                    The value column can't be inferred
                    {preview.columnNames ? ` (columns: ${preview.columnNames.join(', ')})` : ''}. Pick the column to
                    evaluate above.
                </>
            )
        case 'missing-column':
            return (
                <>
                    Column "{preview.column}" is no longer returned by the query
                    {preview.columnNames ? ` (columns: ${preview.columnNames.join(', ')})` : ''}. Pick another column to
                    evaluate.
                </>
            )
        case 'not-numeric':
            return `The evaluated value (${preview.value}) isn't a number. Pick a numeric column to evaluate.`
    }
}

/** Shows what the SQL alert would evaluate right now, surfacing shape problems before the first check. */
export function HogQLAlertPreviewBanner({
    preview,
    conditionType,
}: {
    preview: HogQLAlertPreview | null
    conditionType?: AlertConditionType
}): JSX.Element {
    if (preview === null) {
        return (
            <LemonBanner type="info">
                This alert evaluates the SQL insight's result. Load the insight to preview the value.
            </LemonBanner>
        )
    }
    if (preview.status !== 'ok') {
        return (
            <LemonBanner type={preview.status === 'no-rows' ? 'info' : 'warning'}>
                {getHogQLPreviewBannerCopy(preview)}
            </LemonBanner>
        )
    }

    const isRelative =
        conditionType === AlertConditionType.RELATIVE_INCREASE || conditionType === AlertConditionType.RELATIVE_DECREASE
    if (preview.mode === 'any_row') {
        const breaching = preview.breachingRows
        return (
            <HogQLPreviewStatus wouldFire={breaching !== null ? breaching > 0 : null}>
                {breaching !== null ? (
                    <>
                        <strong>{breaching}</strong> of {preview.rowCount} rows are outside the threshold.
                    </>
                ) : (
                    <>{preview.rowCount} rows available. Set a threshold to see which would fire.</>
                )}
            </HogQLPreviewStatus>
        )
    }
    if (isRelative && preview.rowCount < 2) {
        return (
            <LemonBanner type="warning">
                Relative conditions compare the two most recent rows, but the query currently returns only one row.
            </LemonBanner>
        )
    }
    const isFirstRow = preview.mode === 'first_row'
    const evaluatedRow = isFirstRow ? preview.rows[0] : preview.rows[preview.rows.length - 1]
    const wouldFire = preview.breachingRows !== null ? evaluatedRow?.breaching === true : null
    return (
        <HogQLPreviewStatus wouldFire={wouldFire}>
            Current value: <strong>{humanFriendlyNumber(preview.currentValue)}</strong>
            {isRelative && preview.previousValue !== null ? (
                <>
                    . Previous value: <strong>{humanFriendlyNumber(preview.previousValue)}</strong>
                </>
            ) : null}
        </HogQLPreviewStatus>
    )
}
