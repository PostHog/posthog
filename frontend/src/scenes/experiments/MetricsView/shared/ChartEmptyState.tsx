import { IconActivity, IconClock } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { EXPERIMENT_MIN_EXPOSURES_FOR_RESULTS } from '~/scenes/experiments/constants'

import { ErrorChecklist } from './ErrorChecklist'

interface ChartEmptyStateProps {
    height: number
    experimentStarted: boolean
    hasMinimumExposure: boolean
    metric: any
    error?: any
}

export function ChartEmptyState({
    height,
    experimentStarted,
    hasMinimumExposure,
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
            ) : !hasMinimumExposure ? (
                <div className="flex items-center justify-center text-secondary cursor-default text-[12px] font-normal">
                    <LemonTag size="small" className="mr-2">
                        <IconActivity fontSize="1em" />
                    </LemonTag>
                    <span>Waiting for {EXPERIMENT_MIN_EXPOSURES_FOR_RESULTS}+ exposures to show results</span>
                </div>
            ) : (
                <div className="flex items-center justify-center text-secondary cursor-default text-[12px] font-normal">
                    {error?.hasDiagnostics ? (
                        <ErrorChecklist error={error} metric={metric} />
                    ) : (
                        <Tooltip
                            title={
                                error
                                    ? typeof error === 'string'
                                        ? error
                                        : error.message || error.detail || error.error || JSON.stringify(error)
                                    : 'An error occurred'
                            }
                        >
                            <LemonTag size="small" type="danger" className="mr-1 cursor-pointer">
                                Error
                            </LemonTag>
                        </Tooltip>
                    )}
                </div>
            )}
        </div>
    )
}
