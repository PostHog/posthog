import { TableCell, cn } from '@posthog/quill'

import { checkTypeLabel } from './checksConstants'
import { EMPTY_CELL_VALUE, WIDE_ONLY_CELL } from './checkTableLayout'
import type { DataQualityCheckApi } from './generated/api.schemas'

export function QuillCheckDefinitionCells({
    check,
}: {
    check: Pick<DataQualityCheckApi, 'check_type' | 'column_name'>
}): JSX.Element {
    return (
        <>
            <TableCell valign="top" className={cn(WIDE_ONLY_CELL, 'whitespace-nowrap')}>
                {checkTypeLabel(check.check_type)}
            </TableCell>
            <TableCell valign="top" className={WIDE_ONLY_CELL}>
                {check.column_name || EMPTY_CELL_VALUE}
            </TableCell>
        </>
    )
}
