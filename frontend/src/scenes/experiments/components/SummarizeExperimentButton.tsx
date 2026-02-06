import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo } from 'react'

import { IconAI } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { addProductIntent } from 'lib/utils/product-intents'
import { useMaxTool } from 'scenes/max/useMaxTool'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { experimentLogic } from '../experimentLogic'

/**
 * Minimal context sent to the backend for experiment summarization.
 * The backend fetches all detailed experiment data using the experiment_id.
 * This has the benefit that the AI can be called from other places too.
 */
interface MinimalExperimentSummaryContext {
    experiment_id: number | string
    experiment_name: string
    /** ISO8601 timestamp of when the frontend last refreshed the data */
    frontend_last_refresh: string | null
}

function useExperimentSummaryMaxTool(): ReturnType<typeof useMaxTool> {
    const { experiment, orderedPrimaryMetricsWithResults, primaryMetricsResults, secondaryMetricsResults } =
        useValues(experimentLogic)

    // Get the most recent last_refresh timestamp from metric results
    const frontendLastRefresh = useMemo(() => {
        const allResults = [...(primaryMetricsResults || []), ...(secondaryMetricsResults || [])]
        const timestamps = allResults
            .map((r) => r?.last_refresh)
            .filter((t): t is string => typeof t === 'string')
            .sort()
            .reverse()
        return timestamps[0] || null
    }, [primaryMetricsResults, secondaryMetricsResults])

    // Simplified context - backend will fetch full data using experiment_id
    const maxToolContext = useMemo(
        (): MinimalExperimentSummaryContext => ({
            experiment_id: experiment.id,
            experiment_name: experiment.name || 'Unnamed experiment',
            frontend_last_refresh: frontendLastRefresh,
        }),
        [experiment.id, experiment.name, frontendLastRefresh]
    )

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
