import { IconClock } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { MetricErrorState } from '../new/MetricErrorState'

interface ChartEmptyStateProps {
    height: number
    experimentStarted: boolean
    error?: any
    query?: Record<string, any>
    onRetry?: () => void
    /** Disables the "Try again" button (with a tooltip) while a recalculation is already in flight. */
    retryDisabledReason?: string
}

export function ChartEmptyState({
    height,
    experimentStarted,
    error,
    query,
    onRetry,
    retryDisabledReason,
}: ChartEmptyStateProps): JSX.Element | null {
    /**
     * early return if experiment has not started
     */
    if (!experimentStarted) {
        return (
            <div className="flex items-center justify-center text-secondary cursor-default text-[12px] font-normal">
                <LemonTag size="small" className="mr-2">
                    <IconClock fontSize="1em" />
                </LemonTag>
                <span>Waiting for experiment to start&hellip;</span>
            </div>
        )
    }

    /**
     * bail if no error
     */
    if (!error) {
        return null
    }

    return (
        <div
            className="flex items-center justify-center w-full"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ minHeight: `${height}px` }}
        >
            <MetricErrorState
                error={error}
                query={query}
                onRetry={onRetry}
                retryDisabledReason={retryDisabledReason}
                height={height}
            />
        </div>
    )
}
