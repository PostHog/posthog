import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { RATE_LIMITED_MESSAGE } from './evaluationOverviewDisplay'
import type { DetailsLoad, EvaluationDetails } from './evaluationResultDrawerLogic'

export function EvaluationResultDetails({
    load,
    onRetry,
    children,
}: {
    load: DetailsLoad | null
    onRetry: () => void
    children: (details: EvaluationDetails) => JSX.Element
}): JSX.Element {
    if (load?.status === 'ready') {
        return children(load.details)
    }
    if (load?.status === 'error') {
        return (
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span className="text-secondary">
                    {load.failure === 'rate_limited' ? RATE_LIMITED_MESSAGE : "Couldn't load these results."}
                </span>
                <LemonButton
                    size="small"
                    type="secondary"
                    onClick={onRetry}
                    data-attr="evaluation-overview-drawer-retry"
                >
                    Try again
                </LemonButton>
            </div>
        )
    }
    return (
        <div className="flex flex-col gap-2">
            <LemonSkeleton className="h-4 w-full" />
            <LemonSkeleton className="h-4 w-3/4" />
            <LemonSkeleton className="h-4 w-1/2" />
        </div>
    )
}
