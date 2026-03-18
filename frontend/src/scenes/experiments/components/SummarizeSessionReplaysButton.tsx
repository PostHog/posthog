import { useActions, useValues } from 'kea'

import { IconRewindPlay } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useOpenAi } from 'scenes/max/useOpenAi'

import { FEATURE_FLAGS } from '~/lib/constants'
import type { Experiment } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { useSessionReplaySummaryMaxTool } from '../hooks/useSessionReplaySummaryMaxTool'

type SummarizeSessionReplaysButtonProps = {
    experiment: Experiment
}

/**
 * Calls the Max tool to summarize session replays for an experiment.
 * When EXPERIMENT_SESSION_REPLAYS_SKILL flag is enabled, opens PostHog AI with a skill-based prompt.
 * Otherwise, uses the legacy MaxTool approach.
 */
export const SummarizeSessionReplaysButton = ({
    experiment,
}: SummarizeSessionReplaysButtonProps): JSX.Element | null => {
    const { featureFlags } = useValues(featureFlagLogic)
    const { openMax } = useSessionReplaySummaryMaxTool()
    /**
     * The useOpenAi hook is not using OpenAI directly, but rather using the
     * side panel logic to open the AI in a new tab.
     * I know, it has a terrible name. But the side panel logic is being deprecated.
     */
    const { openAi: openPostHogAI } = useOpenAi()
    const { reportExperimentSessionReplaySummaryRequested } = useActions(experimentLogic)

    const useSkill = featureFlags[FEATURE_FLAGS.EXPERIMENT_SESSION_REPLAYS_SKILL]

    // When using MaxTool, openMax is null if the button shouldn't show
    if (!useSkill && !openMax) {
        return null
    }

    const skillPrompt = `Analyze session replays for experiment "${experiment.name}" (ID: ${experiment.id}). Compare user behavior patterns across all variants.`

    return (
        <LemonButton
            size="small"
            onClick={() => {
                reportExperimentSessionReplaySummaryRequested(experiment)
                if (useSkill) {
                    // Open PostHog AI in a new tab with skill-based prompt
                    openPostHogAI(skillPrompt)
                } else if (openMax) {
                    // Use legacy MaxTool approach
                    openMax()
                }
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
