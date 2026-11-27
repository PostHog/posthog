import { Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { TraceCellLoad } from '../../shared/cellLoads'
import { TraceCellValue } from '../../traces/components/TraceCellValue'
import type { ErrorFirstSeen } from '../errorFirstSeenLogic'
import { firstSeenTooltip } from '../firstSeenTooltip'

export interface FirstSeenCellProps {
    /** Undefined until the row's first seen is asked for, which happens right after the row lands. */
    load: TraceCellLoad<ErrorFirstSeen> | undefined
    /** The project's timezone, whose calendar the checked date is in, so the first seen date is shown in it too. */
    timezone: string
}

export function FirstSeenCell({ load, timezone }: FirstSeenCellProps): JSX.Element {
    const value = load?.status === 'ready' ? load.value : null
    return (
        <TraceCellValue status={load?.status ?? 'loading'} skeletonWidth="w-20">
            {value === null ? null : value.firstSeen === null ? (
                <Tooltip title={firstSeenTooltip(value.checkedFrom)}>
                    <span translate="no">-</span>
                </Tooltip>
            ) : (
                <TZLabel
                    time={value.firstSeen}
                    displayTimezone={timezone}
                    formatDate="MMM D, YYYY"
                    formatTime=""
                    title={firstSeenTooltip(value.checkedFrom)}
                    className="whitespace-nowrap"
                />
            )}
        </TraceCellValue>
    )
}
