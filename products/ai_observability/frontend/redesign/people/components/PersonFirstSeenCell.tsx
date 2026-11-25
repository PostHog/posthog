import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import type { TraceCellStatus } from '../../shared/cellLoads'
import { TraceCellValue } from '../../traces/components/TraceCellValue'
import { firstSeenLabel } from '../firstSeenLabel'
import type { PersonFirstSeen } from '../types'

export interface PersonFirstSeenCellProps {
    /** Null until it is read. */
    firstSeen: PersonFirstSeen | null
    status: TraceCellStatus
}

export function PersonFirstSeenCell({ firstSeen, status }: PersonFirstSeenCellProps): JSX.Element {
    const label = firstSeen ? firstSeenLabel(firstSeen.firstSeen, firstSeen.checkedFrom) : null
    return (
        <span className="flex flex-wrap items-center gap-1">
            <TraceCellValue status={status} skeletonWidth="w-20">
                {label ? (
                    <Tooltip title={label.tooltip}>
                        <span className="whitespace-nowrap" translate="no">
                            {label.text}
                        </span>
                    </Tooltip>
                ) : null}
            </TraceCellValue>
            {firstSeen?.isNew ? (
                <LemonTag type="success" size="small">
                    New
                </LemonTag>
            ) : null}
        </span>
    )
}
