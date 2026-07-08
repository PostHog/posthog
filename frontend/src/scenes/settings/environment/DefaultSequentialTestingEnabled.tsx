import { useActions, useValues } from 'kea'

import { LemonCheckbox } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { experimentsConfigLogic } from './experimentsConfigLogic'

export function DefaultSequentialTestingEnabled(): JSX.Element | null {
    const { experimentsConfig, experimentsConfigLoading } = useValues(experimentsConfigLogic)
    const { updateExperimentsConfig } = useActions(experimentsConfigLogic)

    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <LemonCheckbox
            label="Apply sequential testing by default"
            checked={experimentsConfig?.default_sequential_testing_enabled ?? false}
            onChange={(checked) => {
                updateExperimentsConfig({ default_sequential_testing_enabled: checked })
            }}
            disabled={!!restrictionReason || experimentsConfigLoading}
        />
    )
}
