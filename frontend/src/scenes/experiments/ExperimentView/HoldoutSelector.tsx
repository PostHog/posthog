import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonSelect, Tooltip } from '@posthog/lemon-ui'

import { experimentLogic } from '../experimentLogic'

export function HoldoutSelector(): JSX.Element {
    const { experiment, holdouts, isExperimentRunning } = useValues(experimentLogic)
    const { setExperiment, reportExperimentHoldoutAssigned } = useActions(experimentLogic)

    const holdoutOptions = holdouts.map((holdout) => ({
        value: holdout.id,
        label: holdout.name,
    }))
    holdoutOptions.unshift({ value: null, label: 'No holdout' })

    return (
        <div className="mt-3">
            <div className="inline-flex deprecated-space-x-1">
                <h4 className="font-semibold mb-0">Holdout group</h4>
                <Tooltip title="Exclude a stable group of users from the experiment. This cannot be changed once the experiment is launched.">
                    <IconInfo className="text-secondary text-base" />
                </Tooltip>
            </div>
            <div className="mt-1">
                <LemonSelect
                    disabledReason={
                        isExperimentRunning &&
                        !experiment.end_date &&
                        'The holdout group cannot be changed once the experiment is launched.'
                    }
                    size="xsmall"
                    options={holdoutOptions}
                    value={experiment.holdout_id || null}
                    onChange={(value) => {
                        setExperiment({
                            ...experiment,
                            holdout_id: value,
                        })
                        reportExperimentHoldoutAssigned({ experimentId: experiment.id, holdoutId: value })
                    }}
                    data-attr="experiment-holdout-selector"
                />
            </div>
        </div>
    )
}
