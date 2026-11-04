import type { Dayjs } from 'lib/dayjs'
import type { SampleTableContent } from 'scenes/insights/EmptyStates/SampleDataState'

import { renderColumn } from '~/queries/nodes/DataTable/renderColumn'
import { renderColumnMeta } from '~/queries/nodes/DataTable/renderColumnMeta'
import { type SampleRowsSource, samplePlaceholderColumn } from '~/queries/nodes/DataTable/sampleRows'
import type { DataTableNode } from '~/queries/schema/schema-general'
import type { QueryContext } from '~/queries/types'

// The sample card is narrow, so it shows only the first columns of the table
const SAMPLE_TABLE_MAX_COLUMNS = 4

export function buildSampleTable(
    source: SampleRowsSource,
    columns: string[],
    query: DataTableNode,
    context: QueryContext<DataTableNode> | undefined,
    now: Dayjs
): SampleTableContent {
    const shownColumns = columns
        .filter(
            (column) =>
                column !== '*' && !query.hiddenColumns?.includes(column) && !source.excludedColumns.includes(column)
        )
        .slice(0, SAMPLE_TABLE_MAX_COLUMNS)
    const rows = source.buildRows(shownColumns, now)

    return {
        dataAttr: source.dataAttr,
        header: shownColumns.map((column) => renderColumnMeta(column, query, context).title ?? column),
        rows: rows.map(({ result }, rowIndex) =>
            result.map((value, columnIndex) =>
                value === samplePlaceholderColumn
                    ? null
                    : renderColumn(
                          shownColumns[columnIndex],
                          value,
                          result,
                          rowIndex,
                          rows.length,
                          query,
                          undefined,
                          context
                      )
            )
        ),
    }
}
