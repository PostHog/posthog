import { Link } from '@posthog/lemon-ui'

import { FeedbackStepContext } from '../types'

export interface FeedbackStepLinkProps {
    nodeId: string
    steps: FeedbackStepContext
    onSelectStep: (nodeId: string) => void
}

export function FeedbackStepLink({ nodeId, steps, onSelectStep }: FeedbackStepLinkProps): JSX.Element {
    const name = nodeId !== steps.traceId ? steps.stepLabels.get(nodeId) : undefined
    if (name === undefined) {
        return <span className="text-secondary">Whole trace</span>
    }
    return (
        <Link
            onClick={() => onSelectStep(nodeId)}
            className="max-w-60 truncate font-mono"
            title={`Show ${name}`}
            data-attr="trace-view-feedback-step-link"
        >
            {name}
        </Link>
    )
}
