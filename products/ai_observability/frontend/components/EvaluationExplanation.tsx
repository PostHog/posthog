import { useState } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

export function EvaluationExplanation({
    reasoning,
    probability,
}: {
    reasoning?: string
    probability?: number | null
}): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    if (probability != null) {
        return (
            <Tooltip title="The judge's estimated probability that the evaluation criteria are true. This result has no written reasoning.">
                <span>{`${(probability * 100).toFixed(1)}% probability of true`}</span>
            </Tooltip>
        )
    }
    if (!reasoning) {
        return <div className="text-sm text-secondary">No reasoning provided</div>
    }
    return (
        <button
            type="button"
            className="block max-w-2xl text-left text-sm text-default cursor-pointer"
            aria-expanded={expanded}
            title={expanded ? 'Click to collapse' : 'Click to read all'}
            onClick={() => setExpanded(!expanded)}
            data-attr="llma-evaluation-explanation-toggle"
        >
            <span className={expanded ? 'whitespace-pre-wrap' : 'line-clamp-2'}>{reasoning}</span>
        </button>
    )
}
