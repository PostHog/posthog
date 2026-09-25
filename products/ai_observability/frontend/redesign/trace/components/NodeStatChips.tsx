import { LemonTag } from '@posthog/lemon-ui'

import { NodeStats } from '../types'
import { statParts } from './formatStats'

export interface NodeStatChipsProps {
    stats: NodeStats
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
