import { IconInfo } from '@posthog/icons'
import { LemonSelect, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { experimentLogic } from '../experimentLogic'

export function HoldoutSelector(): JSX.Element {
    const { experiment, holdouts, isExperimentRunning } = useValues(experimentLogic)
    const { setExperiment, updateExperiment } = useActions(experimentLogic)

    const holdoutOptions = holdouts.map((holdout) => ({
        value: holdout.id,
        label: holdout.name,
    }))
    holdoutOptions.unshift({ value: null, label: 'No holdout' })

    return (
        <div className="mt-2">
            <div className="inline-flex space-x-1">
                <h4 className="font-semibold mb-0">Holdout group</h4>
                <Tooltip title="Exclude a stable group of users from the experiment. This cannot be changed once the experiment is launched.">
                    <IconInfo className="text-muted-alt text-base" />
                </Tooltip>
            </div>
            <div className="mt-2">
                <LemonSelect
                    disabledReason={
                        isExperimentRunning &&
                        !experiment.end_date &&
                        'The holdout group cannot be changed once the experiment is launched.'
                    }
                    size="xsmall"
                    options={holdoutOptions}
                    value={experiment.holdout || null}
                    onChange={(value) => {
                        setExperiment({
                            ...experiment,
                            holdout: value,
                        })
                        updateExperiment({ holdout: value })
                    }}
                    data-attr="experiment-holdout-selector"
                />
            </div>
        </div>
    )
}
