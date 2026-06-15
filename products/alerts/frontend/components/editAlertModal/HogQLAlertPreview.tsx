import { LemonBanner, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { HOGQL_ANY_ROW_MAX_ROWS, HogQLAlertPreview, HogQLAlertPreviewRow } from 'lib/components/Alerts/alertFormLogic'
import { humanFriendlyNumber, pluralize } from 'lib/utils'

import { AlertConditionType } from '~/queries/schema/schema-general'

const PREVIEW_TABLE_MAX_ROWS = 10

/** Per-row view of what the alert would evaluate: breaching rows first (any-row) or the most
 * recent rows (last-row), capped to keep the modal compact. Shown even before a threshold is set —
 * seeing the rows is how users orient on what to alert on; the breach column appears once bounds exist. */
export function HogQLAlertPreviewRowsTable({
    preview,
}: {
    preview: Extract<HogQLAlertPreview, { status: 'ok' }>
}): JSX.Element | null {
    const isAnyRow = preview.mode === 'any_row'
    const rows = isAnyRow
        ? [...preview.rows].sort((a, b) => Number(b.breaching) - Number(a.breaching)).slice(0, PREVIEW_TABLE_MAX_ROWS)
        : preview.rows.slice(-PREVIEW_TABLE_MAX_ROWS) // chronological: the most recent rows
    const hiddenCount = preview.rows.length - rows.length
    const showStatus = preview.breachingRows !== null

    return (
        <div className="deprecated-space-y-1">
            {hiddenCount > 0 && (
                // The note sits above the table in both modes: in last-row mode the trimmed rows
                // are older ones (below would read as newer data), and any-row matches for consistency.
                <div className="text-muted text-xs">+{pluralize(hiddenCount, isAnyRow ? 'more row' : 'older row')}</div>
            )}
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
                            row.value !== null ? humanFriendlyNumber(row.value) : '—',
                    },
                    ...(showStatus
                        ? [
                              {
                                  title: '',
                                  // In last-row mode only the final row is evaluated, so only it gets a
                                  // tag — historical rows stay untagged (the banner carries the
                                  // outside-threshold count) instead of reading as live breaches.
                                  render: (_: unknown, row: HogQLAlertPreviewRow, index: number) =>
                                      isAnyRow || index === rows.length - 1 ? (
                                          row.breaching ? (
                                              <LemonTag type="warning">breach</LemonTag>
                                          ) : (
                                              <LemonTag type="success">ok</LemonTag>
                                          )
                                      ) : null,
                              },
                          ]
                        : []),
                ]}
            />
        </div>
    )
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
                This alert evaluates the SQL insight's result — load the insight to preview the value.
            </LemonBanner>
        )
    }
    switch (preview.status) {
        case 'no-rows':
            return (
                <LemonBanner type="info">
                    The query currently returns no rows — the alert evaluates this as 0, so a lower bound can still
                    fire.
                </LemonBanner>
            )
        case 'too-many-rows':
            return (
                <LemonBanner type="warning">
                    Any-row alerts evaluate at most {HOGQL_ANY_ROW_MAX_ROWS} rows, but the query returns{' '}
                    {preview.rowCount} — add a LIMIT or aggregate the query, or the alert will fail to evaluate.
                </LemonBanner>
            )
        case 'bad-shape':
            return (
                <LemonBanner type="warning">
                    The query result isn't plain rows of values — the alert requires a query returning rows with a
                    numeric column.
                </LemonBanner>
            )
        case 'ambiguous-columns':
            return (
                <LemonBanner type="warning">
                    The value column can't be inferred
                    {preview.columnNames ? ` (columns: ${preview.columnNames.join(', ')})` : ''} — pick the column to
                    evaluate above.
                </LemonBanner>
            )
        case 'missing-column':
            return (
                <LemonBanner type="warning">
                    Column "{preview.column}" is no longer returned by the query
                    {preview.columnNames ? ` (columns: ${preview.columnNames.join(', ')})` : ''} — pick another column
                    to evaluate.
                </LemonBanner>
            )
        case 'not-numeric':
            return (
                <LemonBanner type="warning">
                    The evaluated value ({preview.value}) isn't a number — pick a numeric column to evaluate.
                </LemonBanner>
            )
        case 'ok': {
            const isRelative =
                conditionType === AlertConditionType.RELATIVE_INCREASE ||
                conditionType === AlertConditionType.RELATIVE_DECREASE
            const columnLabel = preview.columnName ? (
                <>
                    the <strong>{preview.columnName}</strong> column
                </>
            ) : (
                'the result'
            )
            if (preview.mode === 'any_row') {
                const breaching = preview.breachingRows
                return (
                    <LemonBanner type={breaching ? 'warning' : 'info'}>
                        The alert checks every row of {columnLabel}
                        {breaching !== null ? (
                            <>
                                {' '}
                                — currently <strong>{breaching}</strong> of {preview.rowCount} rows breach the threshold
                                {breaching > 0 ? ', so the alert would fire on its next check' : ''}.
                            </>
                        ) : (
                            <>. Set a threshold to preview which rows would breach.</>
                        )}
                    </LemonBanner>
                )
            }
            if (isRelative && preview.rowCount < 2) {
                return (
                    <LemonBanner type="warning">
                        Relative conditions compare the last two rows, but the query currently returns only one row.
                    </LemonBanner>
                )
            }
            return (
                <LemonBanner type="info">
                    The alert evaluates the last row of {columnLabel} — currently{' '}
                    <strong>{humanFriendlyNumber(preview.currentValue)}</strong>
                    {isRelative && preview.previousValue !== null ? (
                        <>
                            {' '}
                            vs <strong>{humanFriendlyNumber(preview.previousValue)}</strong> in the previous row
                        </>
                    ) : null}
                    . Order the query chronologically so the last row is the most recent value.
                    {!isRelative && preview.breachingRows !== null ? (
                        <>
                            {' '}
                            Right now <strong>{preview.breachingRows}</strong> of its{' '}
                            {pluralize(preview.rowCount, 'row')} {preview.breachingRows === 1 ? 'is' : 'are'} outside
                            the threshold.
                        </>
                    ) : null}
                </LemonBanner>
            )
        }
    }
}
