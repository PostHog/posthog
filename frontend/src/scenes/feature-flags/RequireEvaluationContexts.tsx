import { useActions, useValues } from 'kea'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, TeamMembershipLevel } from 'lib/constants'
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
