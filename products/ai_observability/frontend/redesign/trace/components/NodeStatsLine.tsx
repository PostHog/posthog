import { Fragment } from 'react'

import { cn } from 'lib/utils/css-classes'

import type { TraceNodeStatsApi } from '../../../generated/api.schemas'
import { compactStatParts, statParts } from './formatStats'

export interface NodeStatsLineProps {
    stats: TraceNodeStatsApi
    model?: string | null
    compact?: boolean
    /** Breaks between stats when the line runs out of room, instead of cutting the end off. */
    wrap?: boolean
    className?: string
}

export function NodeStatsLine({
    stats,
    model,
    compact = false,
    wrap = false,
    className,
}: NodeStatsLineProps): JSX.Element | null {
    const parts = [...(compact ? compactStatParts(stats) : statParts(stats)), ...(model ? [model] : [])]
    if (parts.length === 0) {
        return null
    }
    if (!wrap) {
        return <span className={cn('font-mono text-xs text-secondary truncate', className)}>{parts.join(' · ')}</span>
    }
    return (
        <span className={cn('font-mono text-xs text-secondary', className)}>
            {parts.map((part, index) => (
                <Fragment key={index}>
                    {index > 0 ? ' · ' : null}
                    <span className="whitespace-nowrap">{part}</span>
                </Fragment>
            ))}
        </span>
    )
}
