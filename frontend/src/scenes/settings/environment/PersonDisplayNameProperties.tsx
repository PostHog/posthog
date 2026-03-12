import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { PropertySelect } from 'lib/components/PropertySelect/PropertySelect'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES, TeamMembershipLevel } from 'lib/constants'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { teamLogic } from 'scenes/teamLogic'

export function PersonDisplayNameProperties(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const [value, setValue] = useState([] as string[])
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    useEffect(
        () => setValue(currentTeam?.person_display_name_properties || PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES),
        [currentTeam]
    )

    if (!currentTeam) {
        return <LemonSkeleton className="w-1/2 h-4" />
    }

    return (
        <>
            <div className="deprecated-space-y-4">
                <PropertySelect
                    taxonomicFilterGroup={TaxonomicFilterGroupType.PersonProperties}
                    onChange={(properties) => setValue(properties)}
                    selectedProperties={value || []}
                    addText="Add"
                    sortable
                    disabledReason={restrictedReason}
                />
                <LemonButton
                    type="primary"
                    onClick={() =>
                        updateCurrentTeam({
                            person_display_name_properties: value.map((s) => s.trim()).filter((a) => a) || [],
                        })
                    }
                    disabledReason={restrictedReason}
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
