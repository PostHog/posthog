import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ProductIntentContext, addProductIntent } from 'lib/utils/product-intents'
import { useMaxTool } from 'scenes/max/useMaxTool'

import { ProductKey } from '~/types'

import { experimentLogic } from '../experimentLogic'

function useExperimentSummaryMaxTool(): ReturnType<typeof useMaxTool> {
    const { experiment, legacyPrimaryMetricsResults, primaryMetricsResults } = useValues(experimentLogic)

    const maxToolContext = useMemo(() => {
        // Format results for the Max tool - use primary results if available, otherwise legacy
        const resultsToUse = primaryMetricsResults.length > 0 ? primaryMetricsResults : legacyPrimaryMetricsResults
        const formattedResults = resultsToUse
            .map((result, index) => {
                if (!result) {
                    return null
                }

                const metric = experiment.metrics[index]
                const metricName = metric?.name || `Metric ${index + 1}`

                // Extract variant data based on result type
                let variants: any[] = []
                let significant = false
                let p_value = null
                let winner = null

                if ('variants' in result) {
                    variants = result.variants
                    significant = result.significant || false
                    p_value = result.p_value || null

                    // Determine winner if significant
                    if (significant && variants.length > 0) {
                        // For trends experiments
                        if ('count' in variants[0]) {
                            const control = variants.find((v) => v.key === 'control')
                            const test = variants.find((v) => v.key !== 'control')
                            if (control && test) {
                                const controlRate = control.count / (control.exposure || 1)
                                const testRate = test.count / (test.exposure || 1)
                                winner = testRate > controlRate ? test.key : 'control'
                            }
                        }
                        // For funnel experiments
                        else if ('success_count' in variants[0]) {
                            const control = variants.find((v) => v.key === 'control')
                            const test = variants.find((v) => v.key !== 'control')
                            if (control && test) {
                                const controlRate =
                                    control.success_count / (control.success_count + control.failure_count)
                                const testRate = test.success_count / (test.success_count + test.failure_count)
                                winner = testRate > controlRate ? test.key : 'control'
                            }
                        }
                    }
                }

                return {
                    metric_name: metricName,
                    variants,
                    significant,
                    p_value,
                    winner,
                }
            })
            .filter(Boolean)

        return {
            experiment_id: experiment.id,
            experiment_name: experiment.name,
            hypothesis: experiment.description, // Using description as hypothesis
            description: experiment.description,
            variants: experiment.parameters?.feature_flag_variants || [],
            results: formattedResults,
            conclusion: experiment.conclusion,
            conclusion_comment: experiment.conclusion_comment,
        }
    }, [experiment, legacyPrimaryMetricsResults, primaryMetricsResults])

    const shouldShowMaxSummaryTool = useMemo(() => {
        // Show button only if there are results and experiment has started
        const hasLegacyResults = legacyPrimaryMetricsResults.length > 0
        const hasPrimaryResults = primaryMetricsResults.length > 0
        const hasResults = hasLegacyResults || hasPrimaryResults
        const hasStarted = !!experiment.start_date
        return hasResults && hasStarted
    }, [legacyPrimaryMetricsResults, primaryMetricsResults, experiment.start_date])

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
        <LemonButton onClick={openMax} type="secondary" icon={null}>
            Summarize with Max
        </LemonButton>
    )
}
