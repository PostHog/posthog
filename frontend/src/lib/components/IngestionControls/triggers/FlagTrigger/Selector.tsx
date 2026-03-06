import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { FlagSelector } from 'lib/components/FlagSelector'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { IconCancel } from 'lib/lemon-ui/icons'

import { flagTriggerLogic } from './flagTriggerLogic'

export const FlagTriggerSelector = (): JSX.Element => {
    const { flag, featureFlagLoading } = useValues(flagTriggerLogic)
    const { onChange } = useActions(flagTriggerLogic)

    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <div className="flex flex-row justify-start">
            <FlagSelector
                value={flag?.id ?? undefined}
                onChange={(id, key) => {
                    onChange({ id, key, variant: null })
                }}
                disabledReason={(restrictedReason ?? featureFlagLoading) ? 'Loading...' : undefined}
                readOnly={!!restrictedReason || featureFlagLoading}
            />
            {flag && (
                <LemonButton
                    className="ml-2"
                    icon={<IconCancel />}
                    size="small"
                    type="secondary"
                    onClick={() => onChange(null)}
                    title="Clear selected flag"
                    loading={featureFlagLoading}
                    disabledReason={restrictedReason}
                />
            )}
        </div>
    )
}
