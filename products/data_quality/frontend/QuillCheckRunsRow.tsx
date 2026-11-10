import { TableCell, TableRow, Text } from '@posthog/quill'

import type { DataQualityCheckRunApi } from './generated/api.schemas'
import { QuillCheckRunsTable } from './QuillCheckRunsTable'

export interface QuillCheckRunsRowProps {
    colSpan: number
    description?: string | null
    runs: DataQualityCheckRunApi[]
    loading?: boolean
}

export function QuillCheckRunsRow({ colSpan, description, runs, loading }: QuillCheckRunsRowProps): JSX.Element {
    return (
        <TableRow>
            <TableCell colSpan={colSpan}>
                <div className="flex flex-col gap-2">
                    {description && (
                        <Text size="xs" variant="muted" className="m-0">
                            {description}
                        </Text>
                    )}
                    <QuillCheckRunsTable runs={runs} loading={loading} />
                </div>
            </TableCell>
        </TableRow>
    )
}
