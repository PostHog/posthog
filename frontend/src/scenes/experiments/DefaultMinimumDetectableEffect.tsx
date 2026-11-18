import { useActions, useValues } from 'kea'
import { useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { LemonInput, LemonSkeleton } from '@posthog/lemon-ui'
import { NumberFieldGroup, NumberFieldInput, NumberFieldRoot, Skeleton, Slider, Text } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from '~/lib/components/RestrictedArea'
import { TeamMembershipLevel } from '~/lib/constants'
import { useFeatureFlag } from '~/lib/hooks/useFeatureFlag'
import { LemonSlider } from '~/lib/lemon-ui/LemonSlider'
import { experimentsConfigLogic } from '~/scenes/settings/environment/experimentsConfigLogic'

export function DefaultMinimumDetectableEffect(): JSX.Element {
    const { experimentsConfig, experimentsConfigLoading, defaultMinimumDetectableEffect } =
        useValues(experimentsConfigLogic)
    const { updateExperimentsConfig } = useActions(experimentsConfigLogic)

    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const [localValue, setLocalValue] = useState<number | null>(null)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const debouncedUpdate = useDebouncedCallback((value: number) => {
        updateExperimentsConfig({ default_minimum_detectable_effect: value })
        setLocalValue(null)
    }, 500)

    if (!experimentsConfig) {
        return todayRailNav ? <Skeleton className="h-8 w-full max-w-165" /> : <LemonSkeleton className="h-10 w-full" />
    }

    const handleChange = (value: number): void => {
        const clampedValue = Math.max(1, Math.min(100, Math.round(value)))
        setLocalValue(clampedValue)
        debouncedUpdate(clampedValue)
    }

    const displayValue = localValue ?? defaultMinimumDetectableEffect
    const disabledReason = restrictionReason || (experimentsConfigLoading ? 'Loading...' : undefined)

    if (todayRailNav) {
        return (
            <div className="flex items-center gap-3 max-w-165">
                <Slider
                    className="flex-3"
                    value={displayValue}
                    onValueChange={(value) => handleChange(Array.isArray(value) ? value[0] : value)}
                    min={1}
                    max={100}
                    step={1}
                    disabledReason={disabledReason}
                />
                <div className="flex-1 flex items-center gap-1">
                    <NumberFieldRoot
                        className="w-16"
                        value={displayValue}
                        onValueChange={(value: number | null) => handleChange(value || 1)}
                        min={1}
                        max={100}
                        step={1}
                        disabledReason={disabledReason}
                    >
                        <NumberFieldGroup>
                            <NumberFieldInput />
                        </NumberFieldGroup>
                    </NumberFieldRoot>
                    <Text size="xs" variant="muted" render={<span />}>
                        %
                    </Text>
                </div>
            </div>
        )
    }

    return (
        <div className="flex items-center gap-3 max-w-165">
            <div className="flex-[3]">
                <LemonSlider
                    value={displayValue}
                    onChange={handleChange}
                    min={1}
                    max={100}
                    step={1}
                    disabledReason={disabledReason}
                />
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
                    disabledReason={disabledReason}
                />
                <span className="text-muted">%</span>
            </div>
        </div>
    )
}
