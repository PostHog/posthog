import { useActions } from 'kea'

import { IconPlus } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import {
    METRIC_CONTEXTS,
    type MetricContext,
} from 'products/experiments/frontend/modals/ExperimentMetricModal/experimentMetricModalLogic'
import { metricSourceModalLogic } from 'products/experiments/frontend/modals/MetricSourceModal/metricSourceModalLogic'

export const EmptyMetricsPanel = ({
    helpText,
    isLaunched,
    showHelpText = true,
    onAddMetric,
}: {
    helpText?: string
    isLaunched?: boolean
    showHelpText?: boolean
    onAddMetric?: (metricType: MetricContext['type']) => void
} = {}): JSX.Element => {
    const { openMetricSourceModal } = useActions(metricSourceModalLogic)

    const addMetric = (context: MetricContext): void => {
        onAddMetric?.(context.type)
        openMetricSourceModal(context)
    }

    return (
        // Sized off its own width rather than the screen's, so the two buttons stack in a narrow column
        <div className="@container border border-dashed rounded p-8 flex flex-col items-center gap-4">
            <div className="flex flex-col @xl:flex-row gap-3 items-stretch @xl:items-start w-full @xl:w-auto">
                <LemonButton
                    type="secondary"
                    icon={<IconPlus />}
                    onClick={() => addMetric(METRIC_CONTEXTS.primary)}
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
                    onClick={() => addMetric(METRIC_CONTEXTS.secondary)}
                    className="!h-[80px] flex-1 @xl:w-[280px] @xl:flex-none"
                >
                    <div className="flex flex-col gap-0.5 text-left">
                        <span className="font-medium text-sm">Add secondary metric</span>
                        <span className="text-xs text-muted">Provide additional context and detect side effects</span>
                    </div>
                </LemonButton>
            </div>
            {!isLaunched && showHelpText && (
                <div className="max-w-md">
                    <p className="text-xs text-muted">
                        {helpText ??
                            "Add metrics to measure your experiment's impact. You can add them before or after launching."}
                    </p>
                </div>
            )}
        </div>
    )
}
