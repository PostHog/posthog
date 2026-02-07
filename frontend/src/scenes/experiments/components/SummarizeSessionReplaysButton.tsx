import { useActions } from 'kea'

import { IconAI } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import type { Experiment } from '~/types'

import { experimentLogic } from '../experimentLogic'

type SummarizeSessionReplaysButtonProps = {
    experiment: Experiment
}

/**
 * Calls the Max tool to summarize session replays for an experiment.
 */
export const SummarizeSessionReplaysButton = ({
    experiment,
}: SummarizeSessionReplaysButtonProps): JSX.Element | null => {
    const { reportExperimentSessionReplaySummaryRequested } = useActions(experimentLogic)

    return (
        <LemonButton
            size="small"
            onClick={() => {
                reportExperimentSessionReplaySummaryRequested(experiment)
            }}
            type="secondary"
            icon={<IconAI />}
            tooltip="Analyze user behavior patterns in session replays using AI"
        >
            Summarize session replays
        </LemonButton>
    )
}
