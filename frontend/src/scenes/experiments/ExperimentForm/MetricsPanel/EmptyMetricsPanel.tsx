import { useActions } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { METRIC_CONTEXTS } from '~/scenes/experiments/Metrics/experimentMetricModalLogic'
import { metricSourceModalLogic } from '~/scenes/experiments/Metrics/metricSourceModalLogic'

export const EmptyMetricsPanel = ({
    helpText,
    isLaunched,
}: { helpText?: string; isLaunched?: boolean } = {}): JSX.Element => {
    const { openMetricSourceModal } = useActions(metricSourceModalLogic)

    return (
        <div className="flex flex-col gap-4">
            {isLaunched && (
                <LemonBanner type="warning">
                    <div>
                        <strong>No metrics defined</strong>
                    </div>
                    <div>
                        Your experiment is running and events are being collected, but no metric is defined. Add at
                        least one metric to see results. Metrics can be added, removed, or changed at any time.
                    </div>
                </LemonBanner>
            )}
            <div className="border border-dashed rounded p-8 flex flex-col items-center gap-4">
                <div className="flex flex-col sm:flex-row gap-3 items-stretch sm:items-start w-full sm:w-auto">
                    <LemonButton
                        type="secondary"
                        onClick={() => openMetricSourceModal(METRIC_CONTEXTS.primary)}
                        className="!h-[80px] flex-1 sm:w-[280px] sm:flex-none"
                    >
                        <div className="flex items-start gap-3 w-full text-left">
                            <IconPlus className="text-xl shrink-0" />
                            <div className="flex flex-col gap-0.5">
                                <span className="font-medium text-sm">Add primary metric</span>
                                <span className="text-xs text-muted block min-h-[2.5rem]">
                                    Tracks your main hypothesis
                                </span>
                            </div>
                        </div>
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        onClick={() => openMetricSourceModal(METRIC_CONTEXTS.secondary)}
                        className="!h-[80px] flex-1 sm:w-[280px] sm:flex-none"
                    >
                        <div className="flex items-start gap-3 w-full text-left">
                            <IconPlus className="text-xl shrink-0" />
                            <div className="flex flex-col gap-0.5">
                                <span className="font-medium text-sm">Add secondary metric</span>
                                <span className="text-xs text-muted block min-h-[2.5rem]">
                                    Provide additional context and detect side effects
                                </span>
                            </div>
                        </div>
                    </LemonButton>
                </div>
                {!isLaunched && (
                    <div className="max-w-md">
                        <p className="text-xs text-muted">
                            {helpText ??
                                "Add metrics to measure your experiment's impact. You can add them before or after launching."}
                        </p>
                    </div>
                )}
            </div>
        </div>
    )
}
