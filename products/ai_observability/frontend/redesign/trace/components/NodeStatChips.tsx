import { LemonTag } from '@posthog/lemon-ui'

import type { TraceNodeStatsApi } from '../../../generated/api.schemas'
import { statParts } from './formatStats'

export interface NodeStatChipsProps {
    stats: TraceNodeStatsApi
}

export function NodeStatChips({ stats }: NodeStatChipsProps): JSX.Element {
    return (
        <div className="flex flex-wrap gap-1">
            {statParts(stats).map((part) => (
                <LemonTag key={part} weight="normal" className="font-mono">
                    {part}
                </LemonTag>
            ))}
        </div>
    )
}
