import { IconActivity, IconClock } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { EXPERIMENT_MIN_EXPOSURES_FOR_RESULTS } from '../constants'

interface ChartEmptyStateProps {
    width: number
    height: number
    experimentStarted: boolean
    hasMinimumExposure: boolean
    error?: any
}

export function ChartEmptyState({
    width,
    height,
    experimentStarted,
    hasMinimumExposure,
    error,
}: ChartEmptyStateProps): JSX.Element {
    return (
        <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet">
            {!experimentStarted ? (
                <foreignObject x="0" y={height / 2 - 10} width={width} height="20">
                    <div className="flex items-center ml-2 xl:ml-0 xl:justify-center text-secondary cursor-default text-[10px] font-normal">
                        <LemonTag size="small" className="mr-2">
                            <IconClock fontSize="1em" />
                        </LemonTag>
                        <span>Waiting for experiment to start&hellip;</span>
                    </div>
                </foreignObject>
            ) : !hasMinimumExposure ? (
                <foreignObject x="0" y={height / 2 - 10} width={width} height="20">
                    <div className="flex items-center ml-2 xl:ml-0 xl:justify-center text-secondary cursor-default text-[10px] font-normal">
                        <LemonTag size="small" className="mr-2">
                            <IconActivity fontSize="1em" />
                        </LemonTag>
                        <span>
                            Waiting for {EXPERIMENT_MIN_EXPOSURES_FOR_RESULTS}+ exposures per variant to show results
                        </span>
                    </div>
                </foreignObject>
            ) : (
                <foreignObject x={0} y={height / 2 - 10} width={width} height="20">
                    <div className="flex items-center ml-2 xl:ml-0 xl:justify-center text-secondary cursor-default text-[10px] font-normal">
                        {error?.hasDiagnostics ? (
                            <LemonTag size="small" type="highlight" className="mr-2">
                                <IconActivity className="mr-1" fontSize="1em" />
                                <span className="font-semibold">
                                    {(() => {
                                        try {
                                            return Object.values(error.detail).filter((v) => v === false).length
                                        } catch {
                                            return '0'
                                        }
                                    })()}
                                </span>
                                /<span className="font-semibold">{error.metricType === 'trend' ? '3' : '2'}</span>
                            </LemonTag>
                        ) : (
                            <LemonTag size="small" type="danger" className="mr-1">
                                Error
                            </LemonTag>
                        )}
                        <span>Results not yet available</span>
                    </div>
                </foreignObject>
            )}
        </svg>
    )
}
