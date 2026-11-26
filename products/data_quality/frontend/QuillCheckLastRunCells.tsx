import { TableCell } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { EMPTY_CELL_VALUE, WIDE_ONLY_CELL } from './checkTableLayout'
import type { DataQualityCheckApi } from './generated/api.schemas'
import { QuillCheckStatusCell } from './QuillCheckStatusCell'

export function QuillCheckLastRunCells({
    check,
}: {
    check: Pick<DataQualityCheckApi, 'last_status' | 'last_succeeded_at' | 'failing_since' | 'last_run_at'>
}): JSX.Element {
    return (
        <>
            <TableCell valign="top" className={WIDE_ONLY_CELL}>
                <QuillCheckStatusCell check={check} />
            </TableCell>
            <TableCell valign="top" className={WIDE_ONLY_CELL}>
                {check.last_run_at ? <TZLabel time={check.last_run_at} /> : EMPTY_CELL_VALUE}
            </TableCell>
        </>
    )
}
