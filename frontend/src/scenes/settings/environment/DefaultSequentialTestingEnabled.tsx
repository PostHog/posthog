import { useActions, useValues } from 'kea'

import { LemonCheckbox } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useQuillSurface } from 'lib/ui/QuillSurface/quillSurfaceContext'

import { experimentsConfigLogic } from './experimentsConfigLogic'
import { QuillSettingCheckbox } from './QuillSettingCheckbox'

export function DefaultSequentialTestingEnabled(): JSX.Element | null {
    const { experimentsConfig, experimentsConfigLoading } = useValues(experimentsConfigLogic)
    const { updateExperimentsConfig } = useActions(experimentsConfigLogic)

    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const todayRailNav = useQuillSurface()

    const handleChange = (checked: boolean): void => {
        updateExperimentsConfig({ default_sequential_testing_enabled: checked })
    }

    if (todayRailNav) {
        return (
            <QuillSettingCheckbox
                label="Apply sequential testing by default"
                checked={experimentsConfig?.default_sequential_testing_enabled ?? false}
                onCheckedChange={handleChange}
                disabled={experimentsConfigLoading}
                disabledReason={restrictionReason}
            />
        )
    }

    return (
        <LemonCheckbox
            label="Apply sequential testing by default"
            checked={experimentsConfig?.default_sequential_testing_enabled ?? false}
            onChange={handleChange}
            disabled={!!restrictionReason || experimentsConfigLoading}
        />
    )
}
