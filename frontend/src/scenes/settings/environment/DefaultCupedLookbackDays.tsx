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

    const savedValue = experimentsConfig?.default_cuped_lookback_days ?? null
    const displayValue = savedValue ?? DEFAULT_LOOKBACK_DAYS
    const [localValue, setLocalValue] = useState<number | undefined>(displayValue)

    useEffect(() => {
        setLocalValue(displayValue)
    }, [displayValue])

    const isOutOfRange =
        localValue !== undefined &&
        Number.isFinite(localValue) &&
        (localValue < MIN_LOOKBACK_DAYS || localValue > MAX_LOOKBACK_DAYS)
    const isNonFinite = localValue !== undefined && !Number.isFinite(localValue)
    const showDanger = isOutOfRange || isNonFinite

    const commit = (): void => {
        if (showDanger) {
            setLocalValue(displayValue)
            return
        }
        if (localValue === undefined) {
            if (savedValue === null) {
                setLocalValue(displayValue)
                return
            }
            updateExperimentsConfig({ default_cuped_lookback_days: null })
            return
        }
        const rounded = Math.round(localValue)
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
            onChange={(value) => setLocalValue(value)}
            onBlur={commit}
            onPressEnter={commit}
            status={showDanger ? 'danger' : 'default'}
            disabled={!!restrictionReason || experimentsConfigLoading}
            className="w-32"
        />
    )
}
