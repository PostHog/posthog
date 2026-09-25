import { cn } from 'lib/utils/css-classes'

import { NodeStats } from '../types'
import { compactStatParts, statParts } from './formatStats'

export interface NodeStatsLineProps {
    stats: NodeStats
    model?: string | null
    compact?: boolean
    className?: string
}

export function NodeStatsLine({ stats, model, compact = false, className }: NodeStatsLineProps): JSX.Element | null {
    const parts = [...(compact ? compactStatParts(stats) : statParts(stats)), ...(model ? [model] : [])]
    if (parts.length === 0) {
        return null
    }
    return <span className={cn('font-mono text-xs text-secondary truncate', className)}>{parts.join(' · ')}</span>
}
