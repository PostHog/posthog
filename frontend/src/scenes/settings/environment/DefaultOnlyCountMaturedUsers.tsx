import { useActions, useValues } from 'kea'

import { LemonCheckbox } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { experimentsConfigLogic } from './experimentsConfigLogic'

export function DefaultOnlyCountMaturedUsers(): JSX.Element | null {
    const { experimentsConfig, experimentsConfigLoading } = useValues(experimentsConfigLogic)
    const { updateExperimentsConfig } = useActions(experimentsConfigLogic)
    const showOption = useFeatureFlag('EXPERIMENTS_MATURED_USERS_FILTER')

    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    if (!showOption) {
        return null
    }

    return (
        <LemonCheckbox
            label="Require completed conversion window"
            checked={experimentsConfig?.default_only_count_matured_users ?? false}
            onChange={(checked) => {
                updateExperimentsConfig({ default_only_count_matured_users: checked })
            }}
            disabled={!!restrictionReason || experimentsConfigLoading}
        />
    )
}
