import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo } from 'react'

import { IconAI } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ProductIntentContext, addProductIntent } from 'lib/utils/product-intents'
import { useMaxTool } from 'scenes/max/useMaxTool'

import {
    ExperimentMaxBayesianContext,
    ExperimentMaxFrequentistContext,
    ExperimentVariantResultBayesian,
    ExperimentVariantResultFrequentist,
} from '~/queries/schema/schema-general'
import { ProductKey } from '~/types'

import { experimentLogic } from '../experimentLogic'

function useExperimentSummaryMaxTool(): ReturnType<typeof useMaxTool> {
    const { experiment, primaryMetricsResults } = useValues(experimentLogic)

    const maxToolContext = useMemo(() => {
        const statisticalMethod = experiment.stats_config?.method || 'bayesian'
        const isFrequentist = statisticalMethod === 'frequentist'

        const formattedResults = primaryMetricsResults
            .map((result, index) => {
                if (!result) {
                    return null
                }

                const metric = experiment.metrics[index]
                const metricName = metric?.name || `Metric ${index + 1}`

                let variants: (ExperimentMaxBayesianContext | ExperimentMaxFrequentistContext)[] = []

                if (result.variant_results) {
                    variants = result.variant_results.map(
                        (variant: ExperimentVariantResultBayesian | ExperimentVariantResultFrequentist) => {
                            const variantKey = variant.key

                            if (isFrequentist) {
                                const frequentistVariant = variant as ExperimentVariantResultFrequentist
                                return {
                                    key: variantKey,
                                    p_value: frequentistVariant.p_value || 0,
                                    confidence_interval: frequentistVariant.confidence_interval || [0, 0],
                                    significant: frequentistVariant.significant || false,
                                }
                            }
                            const bayesianVariant = variant as ExperimentVariantResultBayesian
                            return {
                                key: variantKey,
                                chance_to_win: bayesianVariant.chance_to_win || 0,
                                credible_interval: bayesianVariant.credible_interval || [0, 0],
                                significant: bayesianVariant.significant || false,
                            }
                        }
                    )
                }

                return {
                    metric_name: metricName,
                    variants,
                }
            })
            .filter(Boolean)

        const contextData = {
            experiment_id: experiment.id,
            experiment_name: experiment.name,
            hypothesis: experiment.description,
            description: experiment.description,
            variants: experiment.parameters?.feature_flag_variants || [],
            results: formattedResults,
            conclusion: experiment.conclusion,
            conclusion_comment: experiment.conclusion_comment,
            statistical_method: statisticalMethod,
        }

        return contextData
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
            Summarize with AI
        </LemonButton>
    )
}
