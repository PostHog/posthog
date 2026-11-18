import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { experimentLogic } from '../experimentLogic'

export const HOLDOUT_HELP =
    'Exclude a stable group of users from the experiment. This cannot be changed once the experiment is launched.'
export const HOLDOUT_LOCKED_REASON = 'The holdout group cannot be changed once the experiment is launched.'

export function useHoldoutSelector(): {
    options: { value: number | null; label: string }[]
    value: number | null
    lockedReason?: string
    onChange: (value: number | null) => void
} {
    const { experiment, holdouts, isExperimentRunning } = useValues(experimentLogic)
    const { setExperiment, reportExperimentHoldoutAssigned } = useActions(experimentLogic)

    return {
        options: [
            { value: null, label: 'No holdout' },
            ...holdouts.map((holdout) => ({ value: holdout.id, label: holdout.name })),
        ],
        value: experiment.holdout_id || null,
        lockedReason: isExperimentRunning ? HOLDOUT_LOCKED_REASON : undefined,
        onChange: (value) => {
            setExperiment({ ...experiment, holdout_id: value })
            reportExperimentHoldoutAssigned({ experimentId: experiment.id, holdoutId: value })
        },
    }
}

export function HoldoutSelector(): JSX.Element {
    const { options: holdoutOptions, value, lockedReason, onChange } = useHoldoutSelector()

    return (
        <div className="mt-3">
            <div className="inline-flex deprecated-space-x-1">
                <h4 className="font-semibold mb-0">Holdout group</h4>
                <Tooltip title={HOLDOUT_HELP}>
                    <IconInfo className="text-secondary text-base" />
                </Tooltip>
            </div>
            <div className="mt-1">
                <LemonSelect
                    disabledReason={lockedReason}
                    size="xsmall"
                    options={holdoutOptions}
                    value={value}
                    onChange={onChange}
                    data-attr="experiment-holdout-selector"
                />
            </div>
        </div>
    )
}
