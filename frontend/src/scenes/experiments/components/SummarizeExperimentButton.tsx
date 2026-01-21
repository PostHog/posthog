import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo } from 'react'

import { IconAI } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { addProductIntent } from 'lib/utils/product-intents'
import { useMaxTool } from 'scenes/max/useMaxTool'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import {
    MaxExperimentMetricResult,
    MaxExperimentSummaryContext,
    ProductIntentContext,
    ProductKey,
} from '~/queries/schema/schema-general'
import { ExperimentStatsMethod } from '~/types'

import { getChanceToWin, getDefaultMetricTitle, getDelta } from '../MetricsView/shared/utils'
import { experimentLogic } from '../experimentLogic'

function useExperimentSummaryMaxTool(): ReturnType<typeof useMaxTool> {
    const { experiment, orderedPrimaryMetricsWithResults, orderedSecondaryMetricsWithResults, exposures } =
        useValues(experimentLogic)

    const maxToolContext = useMemo((): MaxExperimentSummaryContext => {
        const statsMethod = experiment.stats_config?.method || 'bayesian'
        const variantKeys = experiment.parameters?.feature_flag_variants?.map((v: any) => v.key) || []

        const transformMetricsForMax = (metricsWithResults: any[]): MaxExperimentMetricResult[] => {
            return metricsWithResults
                .filter(({ result }) => result?.variant_results)
                .map(({ metric, result, displayIndex }) => {
                    const metricName = `${displayIndex + 1}. ${metric.name || getDefaultMetricTitle(metric)}`

                    const variants =
                        result.variant_results?.map((variant: any) => {
                            const delta = getDelta(variant)

                            if (statsMethod === 'bayesian') {
                                return {
                                    key: variant.key,
                                    chance_to_win: getChanceToWin(variant, metric.goal) ?? null,
                                    credible_interval: variant.credible_interval || null,
                                    delta,
                                    significant: variant.significant || false,
                                }
                            }
                            return {
                                key: variant.key,
                                p_value: variant.p_value || null,
                                confidence_interval: variant.confidence_interval || null,
                                delta,
                                significant: variant.significant || false,
                            }
                        }) || []

                    return {
                        name: metricName,
                        goal: metric.goal || null,
                        variant_results: variants,
                    }
                })
        }

        const primary_metrics_results = transformMetricsForMax(orderedPrimaryMetricsWithResults)
        const secondary_metrics_results = transformMetricsForMax(orderedSecondaryMetricsWithResults)

        return {
            experiment_id: experiment.id,
            experiment_name: experiment.name || 'Unnamed experiment',
            description: experiment.description || null,
            exposures: exposures?.total_exposures || null,
            variants: variantKeys,
            primary_metrics_results,
            secondary_metrics_results,
            stats_method: statsMethod as ExperimentStatsMethod,
        }
    }, [experiment, orderedPrimaryMetricsWithResults, orderedSecondaryMetricsWithResults, exposures])

    const shouldShowMaxSummaryTool = useMemo(() => {
        const hasResults = orderedPrimaryMetricsWithResults.length > 0
        const hasStarted = !!experiment.start_date
        return hasResults && hasStarted
    }, [orderedPrimaryMetricsWithResults, experiment.start_date])

    const maxToolResult = useMaxTool({
        identifier: 'experiment_results_summary',
        context: maxToolContext,
        contextDescription: {
            text: maxToolContext.experiment_name,
            icon: iconForType('experiment'),
        },
        active: shouldShowMaxSummaryTool,
        initialMaxPrompt: `!Summarize the experiment "${experiment.name}"`,
        callback(toolOutput) {
            addProductIntent({
                product_type: ProductKey.EXPERIMENTS,
                intent_context: ProductIntentContext.EXPERIMENT_ANALYZED,
                metadata: {
                    experiment_id: experiment.id,
                },
            })

            if (toolOutput?.error) {
                posthog.captureException(toolOutput?.error || 'Undefined error when summarizing experiment with Max', {
                    action: 'max-ai-experiment-summary-failed',
                    experiment_id: experiment.id,
                    ...toolOutput,
                })
            }
        },
    })

    return maxToolResult
}

export function SummarizeExperimentButton(): JSX.Element | null {
    const { openMax } = useExperimentSummaryMaxTool()
    const { experiment } = useValues(experimentLogic)
    const { reportExperimentAiSummaryRequested } = useActions(experimentLogic)
    if (!openMax) {
        return null
    }

    return (
        <LemonButton
            size="small"
            onClick={() => {
                reportExperimentAiSummaryRequested(experiment)
                openMax()
            }}
            type="secondary"
            icon={<IconAI />}
        >
            Summarize
        </LemonButton>
    )
}
