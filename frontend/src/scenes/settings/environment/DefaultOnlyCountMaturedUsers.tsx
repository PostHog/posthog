import { useActions, useValues } from 'kea'

import { LemonCheckbox } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { experimentsConfigLogic } from './experimentsConfigLogic'
import { QuillSettingCheckbox } from './QuillSettingCheckbox'

export function DefaultOnlyCountMaturedUsers(): JSX.Element | null {
    const { experimentsConfig, experimentsConfigLoading } = useValues(experimentsConfigLogic)
    const { updateExperimentsConfig } = useActions(experimentsConfigLogic)

    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const handleChange = (checked: boolean): void => {
        updateExperimentsConfig({ default_only_count_matured_users: checked })
    }

    if (todayRailNav) {
        return (
            <QuillSettingCheckbox
                label="Require completed conversion window"
                checked={experimentsConfig?.default_only_count_matured_users ?? false}
                onCheckedChange={handleChange}
                disabled={experimentsConfigLoading}
                disabledReason={restrictionReason}
            />
        )
    }

    return (
        <LemonCheckbox
            label="Require completed conversion window"
            checked={experimentsConfig?.default_only_count_matured_users ?? false}
            onChange={handleChange}
            disabled={!!restrictionReason || experimentsConfigLoading}
        />
    )
}
