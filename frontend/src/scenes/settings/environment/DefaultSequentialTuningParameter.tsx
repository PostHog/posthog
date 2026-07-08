import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonInput } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import {
    DEFAULT_SEQUENTIAL_TUNING_PARAMETER,
    MAX_SEQUENTIAL_TUNING_PARAMETER,
} from 'scenes/experiments/ExperimentView/sequential'

import { experimentsConfigLogic } from './experimentsConfigLogic'

export function DefaultSequentialTuningParameter(): JSX.Element {
    const { experimentsConfig, experimentsConfigLoading } = useValues(experimentsConfigLogic)
    const { updateExperimentsConfig } = useActions(experimentsConfigLogic)

    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const savedValue = experimentsConfig?.default_sequential_tuning_parameter ?? null
    const displayValue = savedValue ?? DEFAULT_SEQUENTIAL_TUNING_PARAMETER
    const [localValue, setLocalValue] = useState<number | undefined>(displayValue)

    useEffect(() => {
        setLocalValue(displayValue)
    }, [displayValue])

    const isInvalid =
        localValue !== undefined &&
        (!Number.isFinite(localValue) || localValue < 1 || localValue > MAX_SEQUENTIAL_TUNING_PARAMETER)

    const commit = (): void => {
        if (isInvalid) {
            setLocalValue(displayValue)
            return
        }
        if (localValue === undefined) {
            if (savedValue === null) {
                setLocalValue(displayValue)
                return
            }
            updateExperimentsConfig({ default_sequential_tuning_parameter: null })
            return
        }
        const rounded = Math.round(localValue)
        if (rounded === savedValue) {
            return
        }
        updateExperimentsConfig({ default_sequential_tuning_parameter: rounded })
    }

    return (
        <LemonInput
            type="number"
            min={1}
            max={MAX_SEQUENTIAL_TUNING_PARAMETER}
            value={localValue}
            onChange={(value) => setLocalValue(value)}
            onBlur={commit}
            onPressEnter={commit}
            status={isInvalid ? 'danger' : 'default'}
            disabled={!!restrictionReason || experimentsConfigLoading}
            className="w-32"
        />
    )
}
