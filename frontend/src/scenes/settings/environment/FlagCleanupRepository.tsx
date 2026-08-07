import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

import { experimentsConfigLogic } from './experimentsConfigLogic'

export function FlagCleanupRepository(): JSX.Element {
    const { experimentsConfig, experimentsConfigUpdating } = useValues(experimentsConfigLogic)
    const { updateExperimentsConfig } = useActions(experimentsConfigLogic)

    const restrictionReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const savedValue = experimentsConfig?.flag_cleanup_repository ?? null
    const [localValue, setLocalValue] = useState<string>(savedValue ?? '')

    useEffect(() => {
        setLocalValue(savedValue ?? '')
    }, [savedValue])

    const trimmed = localValue.trim()
    const unchanged = trimmed === (savedValue ?? '')

    const save = (): void => {
        if (restrictionReason || unchanged || experimentsConfigUpdating) {
            return
        }
        updateExperimentsConfig({ flag_cleanup_repository: trimmed || null })
    }

    return (
        <div className="flex items-center gap-2 max-w-160">
            <LemonInput
                value={localValue}
                onChange={setLocalValue}
                onPressEnter={save}
                placeholder="organization/repository"
                disabled={!!restrictionReason || experimentsConfigUpdating}
                className="flex-1"
            />
            <LemonButton
                type="primary"
                onClick={save}
                loading={experimentsConfigUpdating}
                disabledReason={restrictionReason || (unchanged ? 'No changes to save' : null)}
            >
                Save
            </LemonButton>
            {savedValue !== null && (
                <LemonButton
                    type="secondary"
                    onClick={() => updateExperimentsConfig({ flag_cleanup_repository: null })}
                    loading={experimentsConfigUpdating}
                    disabledReason={restrictionReason}
                >
                    Clear
                </LemonButton>
            )}
        </div>
    )
}
