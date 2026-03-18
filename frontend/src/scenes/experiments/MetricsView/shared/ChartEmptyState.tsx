import { IconClock } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { isLegacyExperimentQuery } from 'scenes/experiments/utils'

import { LegacyErrorChecklist } from '../legacy/LegacyErrorChecklist'
import { MetricErrorState } from '../new/MetricErrorState'
import { ErrorChecklist } from './ErrorChecklist'

interface ChartEmptyStateProps {
    height: number
    experimentStarted: boolean
    metric: any
    error?: any
    query?: Record<string, any>
    onRetry?: () => void
}

export function ChartEmptyState({
    height,
    experimentStarted,
    error,
    metric,
    query,
    onRetry,
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
        // eslint-disable-next-line react/forbid-dom-props
        <div
            className="flex items-center justify-center w-full"
            style={error ? { minHeight: `${height}px` } : { height: `${height}px` }}
        >
            {error.hasDiagnostics ? (
                <ErrorChecklist error={error} metric={metric} />
            ) : (
                // Use rich error state for all other errors
                <MetricErrorState error={error} metric={metric} query={query} onRetry={onRetry} height={height} />
            )}
        </div>
    )
}
