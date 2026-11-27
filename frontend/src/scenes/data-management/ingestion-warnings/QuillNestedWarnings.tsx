import { DataTable, DataTableProps } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { renderWarningDescription } from './ingestionWarningDisplay'
import { IngestionWarning } from './ingestionWarningsLogic'

// In production this list can be huge, so it is paged rather than rendered at once.
const PAGE_SIZE = 20

const COLUMNS: DataTableProps<IngestionWarning, unknown>['columns'] = [
    {
        id: 'description',
        header: 'Description',
        enableSorting: false,
        meta: { expand: true },
        cell: ({ row }) => (
            <div className="min-w-0 whitespace-normal [&_ul]:list-disc [&_ul]:pl-5">
                {renderWarningDescription(row.original)}
            </div>
        ),
    },
    {
        id: 'timestamp',
        header: 'Time',
        enableSorting: false,
        meta: { align: 'right' },
        cell: ({ row }) => <TZLabel time={row.original.timestamp} showSeconds />,
    },
]

/** The warnings of one type, shown inside its expanded row. */
export function QuillNestedWarnings({ warnings }: { warnings: IngestionWarning[] }): JSX.Element {
    return (
        // A click inside the nested list must not collapse the row it sits in.
        <div data-row-click-ignore className="mt-2 cursor-auto">
            <DataTable columns={COLUMNS} data={warnings} fullWidth size="sm" pageSize={PAGE_SIZE} />
        </div>
    )
}
