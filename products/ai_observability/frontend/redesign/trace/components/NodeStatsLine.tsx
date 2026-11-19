import { Fragment } from 'react'

import { cn } from 'lib/utils/css-classes'

import type { TraceNodeStatsApi } from '../../../generated/api.schemas'
import { PartialTotal } from '../../shared/components/PartialTotal'
import { compactStatParts, statParts } from './formatStats'

export interface NodeStatsLineProps {
    stats: TraceNodeStatsApi
    model?: string | null
    compact?: boolean
    /** Breaks between stats when the line runs out of room, instead of cutting the end off. */
    wrap?: boolean
    /** With `wrap`, marks the token counts as computed from the trace's earliest steps only. */
    partial?: boolean
    className?: string
}

export function NodeStatsLine({
    stats,
    model,
    compact = false,
    wrap = false,
    partial = false,
    className,
}: NodeStatsLineProps): JSX.Element | null {
    const parts = [...(compact ? compactStatParts(stats) : statParts(stats)), ...(model ? [model] : [])]
    if (parts.length === 0) {
        return null
    }
    if (!wrap) {
        return <span className={cn('font-mono text-xs text-secondary truncate', className)}>{parts.join(' · ')}</span>
    }
    // The server reads a trace's cost and latency over all of its events, so only the token counts can be partial.
    const partialParts = new Set(partial ? statParts({ ...stats, costUsd: null, latencyMs: null }) : [])
    return (
        <span className={cn('font-mono text-xs text-secondary', className)}>
            {parts.map((part, index) => (
                <Fragment key={index}>
                    {index > 0 ? ' · ' : null}
                    <PartialTotal partial={partialParts.has(part)}>{part}</PartialTotal>
                </Fragment>
            ))}
        </span>
    )
}
