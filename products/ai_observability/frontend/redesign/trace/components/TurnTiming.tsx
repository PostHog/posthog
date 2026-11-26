import clsx from 'clsx'

import { Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { formatLocalizedTime } from 'lib/utils/datetime'

import { formatLatencyMs } from './formatStats'

export interface TurnTimingProps {
    timestamp: string
    waitMs: number | null
    waitSlow: boolean
}

export function TurnTiming({ timestamp, waitMs, waitSlow }: TurnTimingProps): JSX.Element {
    const wait = waitMs === null ? null : formatLatencyMs(waitMs)
    return (
        <div className="flex shrink-0 gap-1 pt-2 text-xxs text-tertiary">
            <TZLabel
                time={timestamp}
                timestampStyle="absolute"
                formatDate=""
                formatTime={formatLocalizedTime().replace(':ss', '')}
                noStyles
            />
            {wait !== null ? (
                <>
                    <span aria-hidden>·</span>
                    <Tooltip title={`The user waited ${wait} for this answer.`}>
                        <span className={clsx(waitSlow && 'text-warning')}>{wait}</span>
                    </Tooltip>
                </>
            ) : null}
        </div>
    )
}
