import { useActions } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonBanner } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { METRIC_CONTEXTS } from 'products/experiments/frontend/modals/ExperimentMetricModal/experimentMetricModalLogic'
import { metricSourceModalLogic } from 'products/experiments/frontend/modals/MetricSourceModal/metricSourceModalLogic'

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
            {/* Sized off its own width rather than the screen's, so the two buttons stack in a narrow column */}
            <div className="@container border border-dashed rounded p-8 flex flex-col items-center gap-4">
                <div className="flex flex-col @xl:flex-row gap-3 items-stretch @xl:items-start w-full @xl:w-auto">
                    <LemonButton
                        type="secondary"
                        icon={<IconPlus />}
                        onClick={() => openMetricSourceModal(METRIC_CONTEXTS.primary)}
                        className="!h-[80px] flex-1 @xl:w-[280px] @xl:flex-none"
                    >
                        <div className="flex flex-col gap-0.5 text-left">
                            <span className="font-medium text-sm">Add primary metric</span>
                            <span className="text-xs text-muted">Tracks your main hypothesis</span>
                        </div>
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        icon={<IconPlus />}
                        onClick={() => openMetricSourceModal(METRIC_CONTEXTS.secondary)}
                        className="!h-[80px] flex-1 @xl:w-[280px] @xl:flex-none"
                    >
                        <div className="flex flex-col gap-0.5 text-left">
                            <span className="font-medium text-sm">Add secondary metric</span>
                            <span className="text-xs text-muted">
                                Provide additional context and detect side effects
                            </span>
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
