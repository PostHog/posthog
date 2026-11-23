import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { Field, FieldLabel, Switch } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

export function RequireEvaluationContexts(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const switchId = useId()

    // Check if evaluation tags feature flag is enabled
    if (!featureFlags[FEATURE_FLAGS.FLAG_EVALUATION_TAGS]) {
        return null
    }

    const isRequiredEnabled = currentTeam?.require_evaluation_contexts || false

    const handleToggle = (enabled: boolean): void => {
        updateCurrentTeam({
            require_evaluation_contexts: enabled,
        })
    }

    if (todayRailNav) {
        return (
            <Field orientation="horizontal" className="w-fit">
                <Switch
                    id={switchId}
                    data-attr="require-evaluation-contexts-switch"
                    checked={isRequiredEnabled}
                    onCheckedChange={handleToggle}
                    disabledReason={restrictedReason}
                />
                <FieldLabel htmlFor={switchId}>Require evaluation contexts for new flags</FieldLabel>
            </Field>
        )
    }

    return (
        <LemonSwitch
            data-attr="require-evaluation-contexts-switch"
            onChange={handleToggle}
            label="Require evaluation contexts for new flags"
            bordered
            checked={isRequiredEnabled}
            disabledReason={restrictedReason}
        />
    )
}
