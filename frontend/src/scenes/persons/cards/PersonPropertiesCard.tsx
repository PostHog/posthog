import { PropertiesTable } from 'lib/components/PropertiesTable/PropertiesTable'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { useMemo } from 'react'
import { urls } from 'scenes/urls'

import { PersonType, PersonsTabType, PropertyDefinitionType } from '~/types'

export function PersonPropertiesCard({ person }: { person: PersonType }): JSX.Element {
    const propertySummary = useMemo(() => {
        const properties = person.properties || {}

        // Filter out object values and limit to most important properties
        const filteredEntries = Object.entries(properties).filter(
            ([_, value]) => typeof value !== 'object' || value === null
        )

        // Define priority order for important properties
        const priorityProperties = [
            'email',
            '$email',
            'name',
            '$name',
            'first_name',
            'last_name',
            '$browser',
            '$os',
            '$geoip_country_code',
            'utm_source',
            'utm_medium',
            'utm_campaign',
            '$initial_referring_domain',
            '$initial_current_url',
        ]

        // Sort by priority, then alphabetically
        const sortedEntries = filteredEntries.sort(([aKey], [bKey]) => {
            const aPriority = priorityProperties.indexOf(aKey)
            const bPriority = priorityProperties.indexOf(bKey)

            if (aPriority !== -1 && bPriority !== -1) {
                return aPriority - bPriority
            }
            if (aPriority !== -1) {
                return -1
            }
            if (bPriority !== -1) {
                return 1
            }

            return aKey.localeCompare(bKey)
        })

        // Take top 8 properties
        return Object.fromEntries(sortedEntries.slice(0, 8))
    }, [person.properties])

    return (
        <div className="flex flex-col gap-2">
            <PropertiesTable type={PropertyDefinitionType.Person} properties={propertySummary || {}} embedded={false} />
            <div className="flex justify-end">
                <LemonButton
                    type="secondary"
                    size="small"
                    to={urls.personByDistinctId(person.distinct_ids[0]) + '#activeTab=' + PersonsTabType.PROPERTIES}
                >
                    View all properties
                </LemonButton>
            </div>
        </div>
    )
}
