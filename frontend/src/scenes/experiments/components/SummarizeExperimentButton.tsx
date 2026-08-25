import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo } from 'react'

import { IconSparkles } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { addProductIntent } from 'lib/utils/product-intents'
import { useMaxTool } from 'scenes/max/useMaxTool'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

import { experimentLogic } from '../experimentLogic'
import { isLaunched } from '../experimentsLogic'

/**
 * Minimal context sent to the backend for experiment summarization.
 * The backend fetches all detailed experiment data using the experiment_id.
 * This has the benefit that the AI can be called from other places too.
 */
interface MinimalExperimentSummaryContext {
    experiment_id: number | string
    experiment_name: string
}

function useExperimentSummaryMaxTool(): ReturnType<typeof useMaxTool> {
    const { experiment, orderedPrimaryMetricsWithResults } = useValues(experimentLogic)

    // Simplified context - backend will fetch full data using experiment_id
    const maxToolContext = useMemo(
        (): MinimalExperimentSummaryContext => ({
            experiment_id: experiment.id,
            experiment_name: experiment.name || 'Unnamed experiment',
        }),
        [experiment.id, experiment.name]
    )

    const shouldShowMaxSummaryTool = useMemo(() => {
        const hasResults = orderedPrimaryMetricsWithResults.length > 0
        const hasStarted = isLaunched(experiment)
        return hasResults && hasStarted
    }, [orderedPrimaryMetricsWithResults, experiment.status, experiment.start_date, experiment.end_date, experiment])

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

    useAttachedContext(
        shouldShowMaxSummaryTool
            ? [{ type: 'experiment', key: experiment.id, label: experiment.name || 'Unnamed experiment' }]
            : null
    )

    return maxToolResult
}

/**
 * Icon-only spark affordance that opens PostHog AI to summarize experiment results.
 * Styled after the MaxTool corner button.
 */
export function SummarizeExperimentButton(): JSX.Element | null {
    const { openMax } = useExperimentSummaryMaxTool()
    const { experiment } = useValues(experimentLogic)
    const { reportExperimentAiSummaryRequested } = useActions(experimentLogic)
    if (!openMax) {
        return null
    }

    return (
        <Tooltip title="Summarize results with PostHog AI" placement="top-end" delayMs={0}>
            <button
                type="button"
                aria-label="Summarize results with PostHog AI"
                data-attr="experiment-summarize-results"
                className="size-6 shrink-0 cursor-pointer rounded-md border border-dashed border-ai bg-ai/08 backdrop-blur-[2px] transition duration-50 hover:scale-110 dark:bg-ai/20"
                onClick={() => {
                    reportExperimentAiSummaryRequested(experiment)
                    openMax()
                }}
            >
                <IconSparkles className="relative size-full p-1 text-ai dark:text-white" />
            </button>
        </Tooltip>
    )
}
