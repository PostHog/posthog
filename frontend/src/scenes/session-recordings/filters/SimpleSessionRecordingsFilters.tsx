import { LemonButton, LemonMenu } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconPlus } from 'lib/lemon-ui/icons'
import { useMemo } from 'react'
import { teamLogic } from 'scenes/teamLogic'

import { EntityTypes, FilterType, PropertyFilterType, PropertyOperator, RecordingFilters } from '~/types'

export const SimpleSessionRecordingsFilters = ({
    filters,
    setFilters,
    localFilters,
    setLocalFilters,
    onClickAdvancedFilters,
}: {
    filters: RecordingFilters
    setFilters: (filters: RecordingFilters) => void
    localFilters: FilterType
    setLocalFilters: (localFilters: FilterType) => void
    onClickAdvancedFilters: () => void
}): JSX.Element => {
    const { currentTeam } = useValues(teamLogic)

    const displayNameProperties = useMemo(() => currentTeam?.person_display_name_properties ?? [], [currentTeam])

    const pageviewEvent = localFilters.events?.find((event) => event.id === '$pageview')

    const personProperties = filters.properties || []
    const eventProperties = pageviewEvent?.properties || []

    const onClickPersonProperty = (key: string): void => {
        setFilters({
            ...filters,
            properties: [
                ...personProperties,
                { type: PropertyFilterType.Person, key: key, operator: PropertyOperator.Exact },
            ],
        })
    }

    const onClickCurrentUrl = (): void => {
        const events = filters.events || []
        setLocalFilters({
            ...filters,
            events: [
                ...events,
                {
                    id: '$pageview',
                    name: '$pageview',
                    type: EntityTypes.EVENTS,
                    properties: [
                        { type: PropertyFilterType.Event, key: '$current_url', operator: PropertyOperator.Exact },
                    ],
                },
            ],
        })
    }

    const items = useMemo(() => {
        const keys = personProperties.map((p) => p.key)

        const properties = [
            !keys.includes('$geoip_country_name') && {
                label: 'Country',
                key: '$geoip_country_name',
                onClick: () => onClickPersonProperty('$geoip_country_name'),
            },
            !keys.includes('') && {
                label: 'URL',
                key: '$current_url',
                onClick: onClickCurrentUrl,
            },
        ]

        displayNameProperties.forEach((property) => {
            properties.push(
                !keys.includes(property) && {
                    label: property,
                    key: property,
                    onClick: () => onClickPersonProperty(property),
                }
            )
        })

        return properties.filter(Boolean)
    }, [displayNameProperties, personProperties])

    return (
        <div className="space-y-1">
            <PropertyFilters
                pageKey="session-recordings"
                taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties]}
                propertyFilters={personProperties}
                onChange={(properties) => setFilters({ properties })}
                allowNew={false}
            />
            <PropertyFilters
                pageKey="session-recordings-$current_url"
                taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                propertyFilters={eventProperties}
                onChange={(properties) => {
                    setLocalFilters({
                        ...filters,
                        events:
                            properties.length > 0
                                ? [
                                      {
                                          id: '$pageview',
                                          name: '$pageview',
                                          type: EntityTypes.EVENTS,
                                          properties: properties,
                                      },
                                  ]
                                : [],
                    })
                }}
                allowNew={false}
            />
            <LemonMenu
                items={[
                    {
                        title: 'Choose property',
                        items: items,
                    },
                    {
                        items: [{ label: 'Use advanced filters', onClick: onClickAdvancedFilters }],
                    },
                ]}
            >
                <LemonButton size="small" type="secondary" icon={<IconPlus />} />
            </LemonMenu>
        </div>
    )
}
