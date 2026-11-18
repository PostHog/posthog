import { useActions, useValues } from 'kea'

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { CONFIDENCE_LEVEL_OPTIONS } from 'products/experiments/frontend/constants'

import { experimentsConfigLogic } from './experimentsConfigLogic'

export function DefaultExperimentConfidenceLevel(): JSX.Element {
    const { experimentsConfig, experimentsConfigLoading } = useValues(experimentsConfigLogic)
    const { updateExperimentsConfig } = useActions(experimentsConfigLogic)

    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const currentValue = Number(experimentsConfig?.default_experiment_confidence_level ?? 0.95)

    const handleChange = (value: number | null): void => {
        if (value === null) {
            return
        }
        updateExperimentsConfig({ default_experiment_confidence_level: value })
    }

    const disabledReason = experimentsConfigLoading ? 'Loading...' : restrictedReason

    if (todayRailNav) {
        return (
            <Select
                items={CONFIDENCE_LEVEL_OPTIONS}
                value={currentValue}
                onValueChange={(value) => handleChange(value as number | null)}
            >
                <SelectTrigger className="w-fit" disabledReason={disabledReason}>
                    <SelectValue />
                </SelectTrigger>
                <SelectContent>
                    {CONFIDENCE_LEVEL_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                            {option.label}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        )
    }

    return (
        <LemonSelect
            value={currentValue}
            onChange={handleChange}
            options={CONFIDENCE_LEVEL_OPTIONS}
            disabledReason={disabledReason}
        />
    )
}
