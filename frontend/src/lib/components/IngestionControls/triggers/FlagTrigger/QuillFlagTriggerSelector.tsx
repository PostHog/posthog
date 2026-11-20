import { useActions, useValues } from 'kea'

import { Button } from '@posthog/quill'

import { FlagSelector } from 'lib/components/FlagSelector'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { IconCancel } from 'lib/lemon-ui/icons'

import { flagTriggerLogic } from './flagTriggerLogic'

export function QuillFlagTriggerSelector(): JSX.Element {
    const { flag, featureFlagLoading } = useValues(flagTriggerLogic)
    const { onChange } = useActions(flagTriggerLogic)

    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <div className="flex flex-wrap items-center gap-2">
            <FlagSelector
                value={flag?.id ?? undefined}
                onChange={(id, key) => {
                    onChange({ id, key, variant: null })
                }}
                disabledReason={restrictedReason ?? (featureFlagLoading ? 'Loading...' : undefined)}
                readOnly={!!restrictedReason || featureFlagLoading}
            />
            {flag && (
                <Button
                    variant="outline"
                    size="icon"
                    aria-label="Clear selected flag"
                    tooltip="Clear selected flag"
                    onClick={() => onChange(null)}
                    loading={featureFlagLoading}
                    disabledReason={restrictedReason}
                >
                    <IconCancel />
                </Button>
            )}
        </div>
    )
}
