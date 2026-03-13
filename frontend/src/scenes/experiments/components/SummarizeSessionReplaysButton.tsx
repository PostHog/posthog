import { useActions, useValues } from 'kea'

import { IconRewindPlay } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { useOpenAi } from 'scenes/max/useOpenAi'

import type { Experiment } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { isLaunched } from '../experimentsLogic'

type SummarizeSessionReplaysButtonProps = {
    experiment: Experiment
}

/**
 * Opens PostHog AI to analyze session replays for an experiment using the analyzing-experiment-session-replays skill.
 */
export const SummarizeSessionReplaysButton = ({
    experiment,
}: SummarizeSessionReplaysButtonProps): JSX.Element | null => {
    /**
     * The useOpenAi hook is not using OpenAI directly, but rather using the
     * side panel logic to open the AI in a new tab.
     * I know, it has a terrible name. But the side panel logic is being deprecated.
     */
    const { openAi: openPostHogAI } = useOpenAi()
    const { reportExperimentSessionReplaySummaryRequested } = useActions(experimentLogic)
    const { orderedPrimaryMetricsWithResults } = useValues(experimentLogic)

    const resultsCount = orderedPrimaryMetricsWithResults.length
    const hasResults = resultsCount > 0
    const hasStarted = isLaunched(experiment)
    const shouldShowButton = hasResults && hasStarted

    if (!shouldShowButton) {
        return null
    }

    const skillPrompt = `Analyze session replays for experiment "${experiment.name}" (ID: ${experiment.id}). Compare user behavior patterns across all variants.`

    return (
        <LemonButton
            size="small"
            onClick={() => {
                reportExperimentSessionReplaySummaryRequested(experiment)
                openPostHogAI(skillPrompt)
            }}
            type="secondary"
            icon={<IconRewindPlay />}
            tooltip="Use AI to analyze session replays and identify patterns in user behavior across experiment variants. Discover insights about how users interact with your variants."
        >
            Summarize session replays
            <LemonTag type="highlight" size="small" className="ml-1">
                Beta
            </LemonTag>
        </LemonButton>
    )
}
