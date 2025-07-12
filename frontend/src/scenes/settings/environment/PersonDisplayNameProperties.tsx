import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { PropertySelect } from 'lib/components/PropertySelect/PropertySelect'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES } from 'lib/constants'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { teamLogic } from 'scenes/teamLogic'

export function PersonDisplayNameProperties(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const [value, setValue] = useState([] as string[])

    useEffect(
        () => setValue(currentTeam?.person_display_name_properties || PERSON_DEFAULT_DISPLAY_NAME_PROPERTIES),
        [currentTeam]
    )

    if (!currentTeam) {
        return <LemonSkeleton className="w-1/2 h-4" />
    }

    return (
        <>
            <p>
                Choose which properties of an identified Person will be used for their <b>Display Name</b>. The first
                property to be found on the Person will be used. Drag the items to re-order the priority.
            </p>
            <div className="deprecated-space-y-4">
                <PropertySelect
                    taxonomicFilterGroup={TaxonomicFilterGroupType.PersonProperties}
                    onChange={(properties) => setValue(properties)}
                    selectedProperties={value || []}
                    addText="Add"
                    sortable
                />
                <LemonButton
                    type="primary"
                    onClick={() =>
                        updateCurrentTeam({
                            person_display_name_properties: value.map((s) => s.trim()).filter((a) => a) || [],
                        })
                    }
                >
                    Save
                </LemonButton>
            </div>
        </>
    )
}
