import { IconClock } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { isNoExposuresError } from 'scenes/experiments/metricQueryErrors'
import { isLegacyExperimentQuery } from 'scenes/experiments/utils'

import { LegacyErrorChecklist } from 'products/experiments/frontend/legacy'

import { MetricErrorState } from '../new/MetricErrorState'
import { ErrorChecklist } from './ErrorChecklist'

interface ChartEmptyStateProps {
    height: number
    experimentStarted: boolean
    metric: any
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
    metric,
    query,
    onRetry,
    retryDisabledReason,
}: ChartEmptyStateProps): JSX.Element | null {
    /**
     * early return if experiment has not started
     */
    if (!experimentStarted) {
        return <WaitingState>Waiting for experiment to start&hellip;</WaitingState>
    }

    /**
     * bail if no error
     */
    if (!error) {
        return null
    }

    /**
     * the experiment is running but nobody has been exposed to the baseline variant yet, which is
     * how every experiment starts out, so wait rather than report a failure the user must act on
     */
    if (isNoExposuresError(error)) {
        return <WaitingState>Waiting for exposures&hellip;</WaitingState>
    }

    const isLegacyMetric = isLegacyExperimentQuery(metric)
    /**
     * if it's a legacy metric, use the legacy error checklist
     */
    if (isLegacyMetric) {
        return (
            // eslint-disable-next-line react/forbid-dom-props
            <div className="flex items-center justify-center w-full" style={{ height: `${height}px` }}>
                <LegacyErrorChecklist error={error} metric={metric} />
            </div>
        )
    }

    return (
        <div
            className="flex items-center justify-center w-full"
            // eslint-disable-next-line react/forbid-dom-props
            style={error ? { minHeight: `${height}px` } : { height: `${height}px` }}
        >
            {error.hasDiagnostics ? (
                <ErrorChecklist error={error} metric={metric} />
            ) : (
                // Use rich error state for all other errors
                <MetricErrorState
                    error={error}
                    metric={metric}
                    query={query}
                    onRetry={onRetry}
                    retryDisabledReason={retryDisabledReason}
                    height={height}
                />
            )}
        </div>
    )
}

function WaitingState({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div className="flex items-center justify-center text-secondary cursor-default text-[12px] font-normal">
            <LemonTag size="small" className="mr-2">
                <IconClock fontSize="1em" />
            </LemonTag>
            <span>{children}</span>
        </div>
    )
}
