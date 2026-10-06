import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TeamMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { groupsModel } from '~/models/groupsModel'
import { AnyPropertyFilter } from '~/types'

import { ApplyDefaultFiltersToExistingInsights } from './ApplyDefaultFiltersToExistingInsights'

export function DefaultFiltersConfig(): JSX.Element {
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <div className="mb-4 flex flex-col gap-2">
            <div className="mb-4 flex flex-col gap-2">
                {currentTeam && (
                    <PropertyFilters
                        pageKey="default-filters"
                        propertyFilters={currentTeam.default_filters_config?.filters ?? []}
                        onChange={(filters: AnyPropertyFilter[]) =>
                            updateCurrentTeam({ default_filters_config: { filters } })
                        }
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.PersonProperties,
                            TaxonomicFilterGroupType.EventFeatureFlags,
                            ...groupsTaxonomicTypes,
                            TaxonomicFilterGroupType.Cohorts,
                            TaxonomicFilterGroupType.Elements,
                        ]}
                        disabledReason={restrictedReason ?? undefined}
                    />
                )}
            </div>
            <LemonSwitch
                onChange={(checked) =>
                    updateCurrentTeam({
                        default_filters_config: {
                            filters: currentTeam?.default_filters_config?.filters ?? [],
                            apply_to_new_insights: checked,
                        },
                    })
                }
                checked={!!currentTeam?.default_filters_config?.apply_to_new_insights}
                disabled={currentTeamLoading}
                disabledReason={restrictedReason}
                label="Enable these filters on all new insights"
                bordered
            />
            <ApplyDefaultFiltersToExistingInsights />
        </div>
    )
}
