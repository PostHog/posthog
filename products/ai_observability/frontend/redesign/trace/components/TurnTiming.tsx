import clsx from 'clsx'

import { Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { formatLatencyMs } from './formatStats'
import { isSlowWait } from './turnGaps'

export interface TurnTimingProps {
    timestamp: string
    waitMs: number | null
}

export function TurnTiming({ timestamp, waitMs }: TurnTimingProps): JSX.Element {
    const wait = waitMs === null ? null : formatLatencyMs(waitMs)
    return (
        <div className="flex shrink-0 gap-1 pt-2 text-xxs text-tertiary">
            <TZLabel time={timestamp} timestampStyle="absolute" formatDate="" formatTime="HH:mm" noStyles />
            {wait !== null ? (
                <>
                    <span aria-hidden>·</span>
                    <Tooltip title={`The user waited ${wait} for this answer.`}>
                        <span className={clsx(isSlowWait(waitMs) && 'text-warning')}>{wait}</span>
                    </Tooltip>
                </>
            ) : null}
        </div>
    )
}
