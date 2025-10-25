import { IconClock } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { ErrorChecklist } from './ErrorChecklist'

interface ChartEmptyStateProps {
    height: number
    experimentStarted: boolean
    metric: any
    error?: any
}

export function ChartEmptyState({ height, experimentStarted, error, metric }: ChartEmptyStateProps): JSX.Element {
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
