import { Tooltip } from '@posthog/lemon-ui'

export function EvaluationExplanation({
    reasoning,
    probability,
}: {
    reasoning?: string
    probability?: number | null
}): JSX.Element {
    if (probability != null) {
        return (
            <Tooltip title="The judge's estimated probability that the evaluation criteria are true. This result has no written reasoning.">
                <span>{`${(probability * 100).toFixed(1)}% probability of true`}</span>
            </Tooltip>
        )
    }
    return (
        <Tooltip title={reasoning}>
            <div className="max-w-md cursor-default">
                <div className="text-sm text-default line-clamp-2">{reasoning || 'No reasoning provided'}</div>
            </div>
        </Tooltip>
    )
}
