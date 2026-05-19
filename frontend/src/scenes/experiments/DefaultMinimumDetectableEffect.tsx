import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { LemonInput, LemonSkeleton } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from '~/lib/components/RestrictedArea'
import { TeamMembershipLevel } from '~/lib/constants'
import { LemonSlider } from '~/lib/lemon-ui/LemonSlider'
import { experimentsConfigLogic } from '~/scenes/settings/environment/experimentsConfigLogic'

import { DEFAULT_MDE } from './constants'

export function DefaultMinimumDetectableEffect(): JSX.Element {
    const { experimentsConfig, experimentsConfigLoading } = useValues(experimentsConfigLogic)
    const { updateExperimentsConfig } = useActions(experimentsConfigLogic)

    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const savedValue = experimentsConfig?.default_minimum_detectable_effect ?? DEFAULT_MDE
    const [localValue, setLocalValue] = useState<number | null>(null)

    /**
     * this is saved on change, so we need to debounce.
     */
    const debouncedUpdate = useDebouncedCallback((value: number) => {
        updateExperimentsConfig({ default_minimum_detectable_effect: value })
        setLocalValue(null)
    }, 500)

    // Reset local value when saved value changes from server
    useEffect(() => {
        setLocalValue(null)
    }, [savedValue])

    if (!experimentsConfig) {
        return <LemonSkeleton className="h-10 w-full" />
    }

    const displayValue = localValue ?? savedValue

    const handleChange = (value: number): void => {
        const clampedValue = Math.max(1, Math.min(100, Math.round(value)))
        setLocalValue(clampedValue)
        debouncedUpdate(clampedValue)
    }

    return (
        <div className="flex items-center gap-3 max-w-165">
            <div className="flex-[3]">
                <LemonSlider value={displayValue} onChange={handleChange} min={1} max={100} step={1} />
            </div>
            <div className="flex-1 flex items-center gap-1">
                <LemonInput
                    type="number"
                    value={displayValue}
                    onChange={(value) => handleChange(Number(value) || 1)}
                    min={1}
                    max={100}
                    step={1}
                    className="w-16"
                    disabledReason={restrictionReason || (experimentsConfigLoading ? 'Loading...' : undefined)}
                />
                <span className="text-muted">%</span>
            </div>
        </div>
    )
}
