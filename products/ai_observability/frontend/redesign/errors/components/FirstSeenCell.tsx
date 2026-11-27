import { Tooltip } from '@posthog/lemon-ui'

import type { TraceCellLoad } from '../../shared/cellLoads'
import { TraceCellValue } from '../../traces/components/TraceCellValue'
import type { ErrorFirstSeen } from '../errorFirstSeenLogic'
import { firstSeenLabel } from '../firstSeenLabel'

export interface FirstSeenCellProps {
    /** Undefined until the row's first seen is asked for, which happens right after the row lands. */
    load: TraceCellLoad<ErrorFirstSeen> | undefined
}

export function FirstSeenCell({ load }: FirstSeenCellProps): JSX.Element {
    const label = load?.status === 'ready' ? firstSeenLabel(load.value.firstSeen, load.value.checkedFrom) : null
    return (
        <TraceCellValue status={load?.status ?? 'loading'} skeletonWidth="w-20">
            {label ? (
                <Tooltip title={label.tooltip}>
                    <span className="whitespace-nowrap" translate="no">
                        {label.text}
                    </span>
                </Tooltip>
            ) : null}
        </TraceCellValue>
    )
}
