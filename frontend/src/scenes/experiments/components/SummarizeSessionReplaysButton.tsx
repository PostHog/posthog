import { useActions } from 'kea'

import { IconRewindPlay } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import type { Experiment } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { useSessionReplaySummaryMaxTool } from '../hooks/useSessionReplaySummaryMaxTool'

type SummarizeSessionReplaysButtonProps = {
    experiment: Experiment
}

/**
 * Calls the Max tool to summarize session replays for an experiment.
 */
export const SummarizeSessionReplaysButton = ({
    experiment,
}: SummarizeSessionReplaysButtonProps): JSX.Element | null => {
    const { openMax } = useSessionReplaySummaryMaxTool()
    const { reportExperimentSessionReplaySummaryRequested } = useActions(experimentLogic)

    if (!openMax) {
        return null
    }

    return (
        <LemonButton
            size="small"
            onClick={() => {
                reportExperimentSessionReplaySummaryRequested(experiment)
                openMax()
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
