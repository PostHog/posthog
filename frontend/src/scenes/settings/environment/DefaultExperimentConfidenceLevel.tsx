import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { CONFIDENCE_LEVEL_OPTIONS } from 'scenes/experiments/constants'

import { TeamSettingSelect } from '../components/TeamSettingSelect'

export function DefaultExperimentConfidenceLevel(): JSX.Element {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <TeamSettingSelect
            field="default_experiment_confidence_level"
            options={CONFIDENCE_LEVEL_OPTIONS}
            defaultValue={0.95}
            disabledReason={restrictedReason}
        />
    )
}
