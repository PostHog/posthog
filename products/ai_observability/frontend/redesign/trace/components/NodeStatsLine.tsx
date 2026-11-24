import { Fragment } from 'react'

import { cn } from 'lib/utils/css-classes'

import type { TraceNodeStatsApi } from '../../../generated/api.schemas'
import { PartialTotal } from '../../shared/components/PartialTotal'
import { StatKind, compactStatParts, statParts } from './formatStats'

export interface NodeStatsLineProps {
    stats: TraceNodeStatsApi
    model?: string | null
    compact?: boolean
    /** Breaks between stats when the line runs out of room, instead of cutting the end off. */
    wrap?: boolean
    /** With `wrap`, marks these stats as computed from only some of the trace's steps. */
    partialKinds?: StatKind[]
    className?: string
}

export function NodeStatsLine({
    stats,
    model,
    compact = false,
    wrap = false,
    partialKinds = [],
    className,
}: NodeStatsLineProps): JSX.Element | null {
    const parts = [
        ...(compact ? compactStatParts(stats) : statParts(stats)),
        ...(model ? [{ kind: 'model', text: model }] : []),
    ]
    if (parts.length === 0) {
        return null
    }
    if (!wrap) {
        return (
            <span className={cn('font-mono text-xs text-secondary truncate', className)}>
                {parts.map((part) => part.text).join(' · ')}
            </span>
        )
    }
    return (
        <span className={cn('font-mono text-xs text-secondary', className)}>
            {parts.map((part, index) => (
                <Fragment key={part.kind}>
                    {index > 0 ? ' · ' : null}
                    <PartialTotal partial={partialKinds.some((kind) => kind === part.kind)}>{part.text}</PartialTotal>
                </Fragment>
            ))}
        </span>
    )
}
