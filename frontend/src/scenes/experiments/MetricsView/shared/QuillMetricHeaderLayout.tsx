import { type ReactNode } from 'react'

import { IconTarget } from '@posthog/icons'
import { Badge, Spinner, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { isMetricThresholdCueVisible } from 'scenes/experiments/ExperimentMetricThreshold'

import type { ExperimentMetric } from '~/queries/schema/schema-general'
import type { MetricRetryInfo } from '~/scenes/experiments/experimentMetricsLogic'
import type { Experiment } from '~/types'

import { MetricRetryDetails } from './MetricRetryState'
import { getDefaultMetricTitle, getMetricTag } from './utils'

/** The quill metric header: the drag handle, the title, its badges and the actions. */
export function QuillMetricHeaderLayout({
    dragHandle,
    metric,
    experiment,
    showRecalculatingTag,
    metricRetry,
    actions,
}: {
    dragHandle?: JSX.Element | null
    metric: ExperimentMetric
    experiment: Experiment
    showRecalculatingTag: boolean
    metricRetry?: MetricRetryInfo
    actions: ReactNode
}): JSX.Element {
    const title = metric.name || getDefaultMetricTitle(metric)

    return (
        <div className="flex items-start gap-1">
            {dragHandle}
            <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex min-w-0 items-start justify-between gap-2">
                    <Text size="sm" weight="semibold" className="m-0 line-clamp-2 min-w-0 break-words">
                        {title}
                    </Text>
                    {actions}
                </div>
                <div className="flex flex-wrap items-center gap-1">
                    {metricRetry ? (
                        <Tooltip>
                            <TooltipTrigger render={<Badge variant="warning" tabIndex={0} />}>
                                <Spinner />
                                Retry {metricRetry.attempt} of {metricRetry.max_attempts}
                            </TooltipTrigger>
                            <TooltipContent className="max-w-96">
                                <MetricRetryDetails retry={metricRetry} />
                            </TooltipContent>
                        </Tooltip>
                    ) : showRecalculatingTag ? (
                        <Badge variant="info">
                            <Spinner />
                            Recalculating
                        </Badge>
                    ) : null}
                    <Badge>{getMetricTag(metric)}</Badge>
                    {isMetricThresholdCueVisible(metric) && (
                        <Tooltip>
                            <TooltipTrigger render={<Badge tabIndex={0} />}>
                                <IconTarget />≥ {metric.threshold}
                            </TooltipTrigger>
                            <TooltipContent>
                                {`Reports the percentage of users whose value reaches or exceeds ${metric.threshold}.`}
                            </TooltipContent>
                        </Tooltip>
                    )}
                    {experiment.parameters?.prompt_metadata && <Badge variant="completed">LLM</Badge>}
                    {metric.goal === 'decrease' && <Badge variant="info">Goal: Decrease</Badge>}
                    {metric.isSharedMetric && <Badge>Shared</Badge>}
                </div>
            </div>
        </div>
    )
}
