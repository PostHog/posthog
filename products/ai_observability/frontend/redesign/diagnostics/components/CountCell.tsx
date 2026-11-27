import { humanFriendlyNumber, percentage } from 'lib/utils/numbers'

import type { TraceCellLoad } from '../../shared/cellLoads'
import { TraceCellValue } from '../../traces/components/TraceCellValue'

export interface CountCellProps {
    value: number
    /** The count's share of a whole, from 0 to 1, read after the row and shown under the count once it lands. */
    share?: TraceCellLoad<number>
}

export function CountCell({ value, share }: CountCellProps): JSX.Element {
    return (
        <span className="inline-flex flex-col items-end tabular-nums" translate="no">
            <span>{humanFriendlyNumber(value)}</span>
            {share?.status === 'ready' ? (
                <span className="text-xs text-secondary">{percentage(share.value, 1)}</span>
            ) : share?.status === 'error' ? (
                <span className="text-xs">
                    <TraceCellValue status="error">{null}</TraceCellValue>
                </span>
            ) : null}
        </span>
    )
}
