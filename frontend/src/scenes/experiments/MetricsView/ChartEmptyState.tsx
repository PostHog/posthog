import { IconActivity, IconClock } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { EXPERIMENT_MIN_EXPOSURES_FOR_RESULTS, EXPERIMENT_MIN_METRIC_EVENTS_FOR_RESULTS } from '../constants'
import { ErrorChecklist } from './ErrorChecklist'

interface ChartEmptyStateProps {
    height: number
    experimentStarted: boolean
    hasEnoughDataForResults: boolean
    metric: any
    error?: any
}

export function ChartEmptyState({
    height,
    experimentStarted,
    hasEnoughDataForResults,
    error,
    metric,
}: ChartEmptyStateProps): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div className="flex items-center justify-center w-full" style={{ height: `${height}px` }}>
            {!experimentStarted ? (
                <div className="flex items-center justify-center text-secondary cursor-default text-[12px] font-normal">
                    <LemonTag size="small" className="mr-2">
                        <IconClock fontSize="1em" />
                    </LemonTag>
                    <span>Waiting for experiment to start&hellip;</span>
                </div>
            ) : !hasEnoughDataForResults ? (
                <div className="flex items-center justify-center text-secondary cursor-default text-[12px] font-normal">
                    <LemonTag size="small" className="mr-2">
                        <IconActivity fontSize="1em" />
                    </LemonTag>
                    <span>
                        Not enough data yet. Waiting for at least {EXPERIMENT_MIN_EXPOSURES_FOR_RESULTS}+ exposures and{' '}
                        {EXPERIMENT_MIN_METRIC_EVENTS_FOR_RESULTS}+ metric events per variant
                    </span>
                </div>
            ) : (
                <div className="flex items-center justify-center text-secondary cursor-default text-[12px] font-normal">
                    {error?.hasDiagnostics ? (
                        <ErrorChecklist error={error} metric={metric} />
                    ) : (
                        <LemonTag size="small" type="danger" className="mr-1 cursor-pointer">
                            Error
                        </LemonTag>
                    )}
                </div>
            )}
        </div>
    )
}
