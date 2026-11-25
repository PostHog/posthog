import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'
import { Button, Skeleton } from '@posthog/quill'

import { PropertySelect } from 'lib/components/PropertySelect/PropertySelect'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES, TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    useEffect(
        () => setValue(currentTeam?.person_display_name_properties || PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES),
        [currentTeam]
    )

    if (!currentTeam) {
        return todayRailNav ? <Skeleton className="h-8 w-1/2" /> : <LemonSkeleton className="w-1/2 h-4" />
    }

    const handleSave = (): void =>
        updateCurrentTeam({
            person_display_name_properties: value.map((s) => s.trim()).filter((a) => a) || [],
        })

    const propertySelect = (
        <PropertySelect
            taxonomicFilterGroup={TaxonomicFilterGroupType.PersonProperties}
            onChange={(properties) => setValue(properties)}
            selectedProperties={value || []}
            addText="Add"
            sortable
            disabledReason={restrictedReason}
        />
    )

    if (todayRailNav) {
        return (
            <div className="flex flex-col items-start gap-2">
                {propertySelect}
                <Button variant="primary" onClick={handleSave} disabledReason={restrictedReason}>
                    Save
                </Button>
            </div>
        )
    }

    return (
        <>
            <div className="deprecated-space-y-4">
                {propertySelect}
                <LemonButton type="primary" onClick={handleSave} disabledReason={restrictedReason}>
                    Save
                </LemonButton>
            </div>
        </>
    )
}
