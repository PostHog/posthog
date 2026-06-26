import { useActions, useValues } from 'kea'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'

import { FeatureFlagFilters } from '~/types'

import { defaultReleaseConditionsLogic } from './defaultReleaseConditionsLogic'
import { FeatureFlagReleaseConditionsCollapsible } from './FeatureFlagReleaseConditionsCollapsible'

export function DefaultReleaseConditions(): JSX.Element {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const { isEnabled, filtersForEditor, hasChanges, defaultReleaseConditionsLoading } =
        useValues(defaultReleaseConditionsLogic)
    const { setLocalEnabled, setLocalGroups, saveDefaultReleaseConditions, discardChanges } =
        useActions(defaultReleaseConditionsLogic)

    return (
        <div className="space-y-4">
            <LemonSwitch
                data-attr="default-release-conditions-switch"
                onChange={setLocalEnabled}
                label="Apply default release conditions to new flags"
                bordered
                checked={isEnabled}
                disabled={defaultReleaseConditionsLoading}
                disabledReason={restrictedReason}
            />

            {isEnabled && (
                <div className="border rounded-lg p-4 space-y-4">
                    <p className="text-sm text-secondary">
                        These conditions will be pre-populated when creating any new feature flag. Users can still
                        modify them during flag creation.
                    </p>

                    <FeatureFlagReleaseConditionsCollapsible
                        id="default-release-conditions"
                        filters={filtersForEditor}
                        onChange={(updatedFilters: FeatureFlagFilters) => {
                            // Mirror the top-level aggregation onto every group; null clears it back to users.
                            const aggregationIndex = updatedFilters.aggregation_group_type_index ?? null
                            setLocalGroups(
                                updatedFilters.groups.map((group) => ({
                                    ...group,
                                    aggregation_group_type_index: aggregationIndex,
                                }))
                            )
                        }}
                        isDisabled={!!restrictedReason}
                        hideEarlyExit
                    />
                </div>
            )}

            {hasChanges && (
                <div className="flex gap-2">
                    <LemonButton
                        type="primary"
                        onClick={saveDefaultReleaseConditions}
                        loading={defaultReleaseConditionsLoading}
                        disabledReason={restrictedReason}
                    >
                        Save changes
                    </LemonButton>
                    <LemonButton type="secondary" onClick={discardChanges} disabledReason={restrictedReason}>
                        Discard changes
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
