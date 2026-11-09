import { Link } from '@posthog/lemon-ui'

import { FeedbackStep } from '../types'

export interface FeedbackStepLinkProps {
    step: FeedbackStep | null
    onSelectStep: (nodeId: string) => void
}

export function FeedbackStepLink({ step, onSelectStep }: FeedbackStepLinkProps): JSX.Element {
    if (!step) {
        return <span className="text-secondary">Whole trace</span>
    }
    return (
        <Link
            onClick={() => onSelectStep(step.id)}
            className="max-w-60 truncate font-mono"
            title={`Show ${step.name}`}
            data-attr="trace-view-feedback-step-link"
        >
            {step.name}
        </Link>
    )
}
