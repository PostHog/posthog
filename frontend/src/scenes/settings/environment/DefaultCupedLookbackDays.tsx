import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonInput } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { DEFAULT_LOOKBACK_DAYS, MAX_LOOKBACK_DAYS, MIN_LOOKBACK_DAYS } from 'scenes/experiments/constants'

import { experimentsConfigLogic } from './experimentsConfigLogic'

export function DefaultCupedLookbackDays(): JSX.Element {
    const { experimentsConfig, experimentsConfigLoading } = useValues(experimentsConfigLogic)
    const { updateExperimentsConfig } = useActions(experimentsConfigLogic)

    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const savedValue = experimentsConfig?.default_cuped_lookback_days ?? DEFAULT_LOOKBACK_DAYS
    const [localValue, setLocalValue] = useState<number>(savedValue)

    useEffect(() => {
        setLocalValue(savedValue)
    }, [savedValue])

    const commit = (value: number): void => {
        if (!Number.isFinite(value)) {
            return
        }
        const rounded = Math.round(value)
        if (rounded < MIN_LOOKBACK_DAYS || rounded > MAX_LOOKBACK_DAYS) {
            return
        }
        if (rounded === savedValue) {
            return
        }
        updateExperimentsConfig({ default_cuped_lookback_days: rounded })
    }

    return (
        <LemonInput
            type="number"
            min={MIN_LOOKBACK_DAYS}
            max={MAX_LOOKBACK_DAYS}
            value={localValue}
            onChange={(value) => {
                if (typeof value === 'number') {
                    setLocalValue(value)
                }
            }}
            onBlur={() => commit(localValue)}
            onPressEnter={() => commit(localValue)}
            disabled={!!restrictionReason || experimentsConfigLoading}
            className="w-32"
        />
    )
}
