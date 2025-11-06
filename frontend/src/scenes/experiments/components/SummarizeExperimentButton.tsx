import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo } from 'react'

import { IconAI } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ProductIntentContext, addProductIntent } from 'lib/utils/product-intents'
import { useMaxTool } from 'scenes/max/useMaxTool'

import { MaxExperimentSummaryContext } from '~/queries/schema/schema-general'
import { ExperimentStatsMethod, ProductKey } from '~/types'

import { experimentLogic } from '../experimentLogic'

function useExperimentSummaryMaxTool(): ReturnType<typeof useMaxTool> {
    const { experiment, primaryMetricsResults } = useValues(experimentLogic)

    const maxToolContext = useMemo((): MaxExperimentSummaryContext => {
        const statsMethod = experiment.stats_config?.method || 'bayesian'
        const variantKeys = experiment.parameters?.feature_flag_variants?.map((v: any) => v.key) || []

        const metricsResults = primaryMetricsResults
            .filter((result) => result?.variant_results)
            .map((result, index) => {
                const metricName = experiment.metrics?.[index]?.name || `Metric ${index + 1}`

                const variants =
                    result.variant_results?.map((variant: any) => {
                        if (statsMethod === 'bayesian') {
                            return {
                                key: variant.key,
                                chance_to_win: variant.chance_to_win || null,
                                credible_interval: variant.credible_interval || null,
                                significant: variant.significant || false,
                            }
                        }
                        return {
                            key: variant.key,
                            p_value: variant.p_value || null,
                            confidence_interval: variant.confidence_interval || null,
                            significant: variant.significant || false,
                        }
                    }) || []

                return {
                    name: metricName,
                    variant_results: variants,
                }
            })

        return {
            experiment_id: experiment.id,
            experiment_name: experiment.name || 'Unnamed experiment',
            description: experiment.description || null,
            variants: variantKeys,
            metrics_results: metricsResults,
            stats_method: statsMethod as ExperimentStatsMethod,
        }
    }, [experiment, primaryMetricsResults])

    const shouldShowMaxSummaryTool = useMemo(() => {
        const hasResults = primaryMetricsResults.length > 0
        const hasStarted = !!experiment.start_date
        return hasResults && hasStarted
    }, [primaryMetricsResults, experiment.start_date])

    const maxToolResult = useMaxTool({
        identifier: 'experiment_results_summary',
        context: maxToolContext,
        active: shouldShowMaxSummaryTool,
        initialMaxPrompt: `Summarize the experiment "${experiment.name}"`,
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

    if (!openMax) {
        return null
    }

    return (
        <LemonButton
            size="small"
            onClick={() => {
                openMax()
            }}
            type="secondary"
            icon={<IconAI />}
        >
            Summarize
        </LemonButton>
    )
}
