import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useMemo } from 'react'

import { useMaxTool } from 'scenes/max/useMaxTool'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { experimentLogic } from '../experimentLogic'

/**
 * Minimal context sent to the backend for session replay summarization.
 * The backend fetches recording counts and filters for each variant.
 */
type MinimalSessionReplaySummaryContext = {
    experiment_id: number | string
    experiment_name: string
}

export const useSessionReplaySummaryMaxTool = (): ReturnType<typeof useMaxTool> => {
    const { experiment, orderedPrimaryMetricsWithResults } = useValues(experimentLogic)

    const maxToolContext = useMemo(
        (): MinimalSessionReplaySummaryContext => ({
            experiment_id: experiment.id,
            experiment_name: experiment.name || 'Unnamed experiment',
        }),
        [experiment.id, experiment.name]
    )

    const resultsCount = orderedPrimaryMetricsWithResults.length
    const shouldShowButton = useMemo(() => {
        const hasResults = resultsCount > 0
        const hasStarted = !!experiment.start_date
        return hasResults && hasStarted
    }, [resultsCount, experiment.start_date])

    const maxToolResult = useMaxTool({
        identifier: 'experiment_session_replays_summary',
        context: maxToolContext,
        contextDescription: {
            text: `Session replays for ${maxToolContext.experiment_name}`,
            icon: iconForType('session_replay'),
        },
        active: shouldShowButton,
        initialMaxPrompt: `!Summarize session replays for experiment "${maxToolContext.experiment_name}"`,
        callback(toolOutput) {
            if (toolOutput?.error) {
                posthog.captureException(
                    toolOutput?.error || 'Undefined error when summarizing session replays with Max',
                    {
                        action: 'max-ai-session-replay-summary-failed',
                        experiment_id: experiment.id,
                        ...toolOutput,
                    }
                )
            } else {
                posthog.capture('experiment session replays analyzed', {
                    experiment_id: experiment.id,
                    has_recordings: (toolOutput?.total_recordings ?? 0) > 0,
                })
            }
        },
    })

    return maxToolResult
}
