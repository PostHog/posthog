import { useActions, useValues } from 'kea'

import { LemonCheckbox } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { experimentsConfigLogic } from './experimentsConfigLogic'
import { QuillSettingCheckbox } from './QuillSettingCheckbox'

export function DefaultCupedEnabled(): JSX.Element | null {
    const { experimentsConfig, experimentsConfigLoading } = useValues(experimentsConfigLogic)
    const { updateExperimentsConfig } = useActions(experimentsConfigLogic)

    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleChange = (checked: boolean): void => {
        updateExperimentsConfig({ default_cuped_enabled: checked })
    }

    if (todayRailNav) {
        return (
            <QuillSettingCheckbox
                label="Enable CUPED by default"
                checked={experimentsConfig?.default_cuped_enabled ?? false}
                onCheckedChange={handleChange}
                disabled={experimentsConfigLoading}
                disabledReason={restrictionReason}
            />
        )
    }

    return (
        <LemonCheckbox
            label="Enable CUPED by default"
            checked={experimentsConfig?.default_cuped_enabled ?? false}
            onChange={handleChange}
            disabled={!!restrictionReason || experimentsConfigLoading}
        />
    )
}
