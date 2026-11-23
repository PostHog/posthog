import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { Field, FieldLabel, Switch } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { teamLogic } from 'scenes/teamLogic'

export function RequireFeatureFlagTags(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const switchId = useId()

    const handleToggle = (enabled: boolean): void => {
        updateCurrentTeam({ feature_flag_policy_config: { require_tags: enabled } })
    }

    if (todayRailNav) {
        return (
            <Field orientation="horizontal" className="w-fit">
                <Switch
                    id={switchId}
                    data-attr="require-feature-flag-tags-switch"
                    checked={currentTeam?.feature_flag_policy_config?.require_tags || false}
                    onCheckedChange={handleToggle}
                    disabled={currentTeamLoading}
                    disabledReason={restrictedReason}
                />
                <FieldLabel htmlFor={switchId}>Require tags on feature flags</FieldLabel>
            </Field>
        )
    }

    return (
        <LemonSwitch
            data-attr="require-feature-flag-tags-switch"
            onChange={handleToggle}
            label="Require tags on feature flags"
            bordered
            checked={currentTeam?.feature_flag_policy_config?.require_tags || false}
            disabled={currentTeamLoading}
            disabledReason={restrictedReason}
        />
    )
}
