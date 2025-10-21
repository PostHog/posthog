import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo } from 'react'

import { IconAI } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ProductIntentContext, addProductIntent } from 'lib/utils/product-intents'
import { useMaxTool } from 'scenes/max/useMaxTool'

import { ProductKey } from '~/types'

import { experimentLogic } from '../experimentLogic'

function useExperimentSummaryMaxTool(): ReturnType<typeof useMaxTool> {
    const { experiment, primaryMetricsResults } = useValues(experimentLogic)

    const maxToolContext = useMemo(() => {
        const resultsToUse = primaryMetricsResults

        const formattedResults = resultsToUse
            .map((result, index) => {
                if (!result) {
                    return null
                }

                const metric = experiment.metrics[index]
                const metricName = metric?.name || `Metric ${index + 1}`

                let variants: any[] = []

                if (result.variant_results) {
                    const allVariants = result.baseline
                        ? [result.baseline, ...result.variant_results]
                        : result.variant_results

                    variants = allVariants.map((variant: any) => {
                        const variantKey = variant.key

                        // Calculate conversion rate if we have the data
                        const numerator = variant.numerator_sum || 0
                        const denominator = variant.number_of_samples || variant.denominator_sum || 0
                        const conversion_rate = denominator > 0 ? numerator / denominator : 0

                        return {
                            key: variantKey,
                            // Extract Bayesian fields from top-level result
                            chance_to_win: result.probability?.[variantKey] || 0,
                            credible_interval: result.credible_intervals?.[variantKey] || [],
                            significant: result.significant || false,
                            // Include variant-specific data
                            count: numerator,
                            exposure: denominator,
                            conversion_rate: conversion_rate,
                            // Include raw data for debugging
                            numerator_sum: variant.numerator_sum,
                            denominator_sum: variant.denominator_sum,
                            number_of_samples: variant.number_of_samples,
                        }
                    })
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
            hypothesis: experiment.description, // Using description as hypothesis
            description: experiment.description,
            variants: experiment.parameters?.feature_flag_variants || [],
            results: formattedResults,
            conclusion: experiment.conclusion,
            conclusion_comment: experiment.conclusion_comment,
        }

        return contextData
    }, [experiment, primaryMetricsResults])

    const shouldShowMaxSummaryTool = useMemo(() => {
        // Show button only if there are primary results and experiment has started
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
        <LemonButton size="small" onClick={openMax} type="secondary" icon={<IconAI />}>
            Summarize with AI
        </LemonButton>
    )
}
