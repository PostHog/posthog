import { IconCheckCircle, IconPullRequest, IconX } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

import { InstallationStepStatus } from './installationProgressLogic'

// Timeline dot for a single step.
export function StepIcon({
    status,
    prState,
}: {
    status: InstallationStepStatus
    prState?: 'open' | 'merged'
}): JSX.Element {
    if (status === 'completed') {
        // GitHub's PR color language: green while open, purple once merged.
        if (prState === 'merged') {
            return <IconPullRequest className="text-purple text-base" />
        }
        if (prState === 'open') {
            return <IconPullRequest className="text-success text-base" />
        }
        return <IconCheckCircle className="text-success text-base" />
    }
    if (status === 'failed') {
        return <IconX className="text-danger text-base" />
    }
    if (status === 'in_progress') {
        return <Spinner className="text-base" textColored />
    }
    return <span className="w-4 h-4 rounded-full border-2 border-border" />
}
