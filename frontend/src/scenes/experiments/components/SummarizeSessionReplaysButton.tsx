import { useActions, useValues } from 'kea'

import { IconRewindPlay } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { FEATURE_FLAGS } from '~/lib/constants'
import { SidePanelTab } from '~/types'
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
    const { openSidePanel } = useActions(sidePanelLogic)
    const { reportExperimentSessionReplaySummaryRequested } = useActions(experimentLogic)

    const useSkill = featureFlags[FEATURE_FLAGS.EXPERIMENT_SESSION_REPLAYS_SKILL]

    // When using MaxTool, openMax is null if the button shouldn't show
    if (!useSkill && !openMax) {
        return null
    }

    const experimentName = experiment.name || 'Unnamed experiment'
    const skillPrompt = `Analyze session replays for experiment "${experimentName}" (ID: ${experiment.id}). Compare user behavior patterns across all variants.`

    return (
        <LemonButton
            size="small"
            onClick={() => {
                reportExperimentSessionReplaySummaryRequested(experiment)
                if (useSkill) {
                    // Open PostHog AI with skill-based prompt
                    openSidePanel(SidePanelTab.Max, skillPrompt)
                } else {
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
