import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useMemo } from 'react'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { EntityTypes, PropertyFilterType, PropertyOperator, RecordingFilters } from '~/types'

export const SimpleSessionRecordingsFilters = ({
    filters,
    setFilters,
}: {
    filters: RecordingFilters
    setFilters: (filters: RecordingFilters) => void
}): JSX.Element => {
    const { currentTeam } = useValues(teamLogic)

    const displayNameProperties = useMemo(() => currentTeam?.person_display_name_properties ?? [], [currentTeam])

    const pageviewEvent = filters.events?.find((event) => event.id === '$pageview')

    const personProperties = filters.properties || []
    const eventProperties = pageviewEvent?.properties || []

    const onClickPersonProperty = (key: string): void => {
        setFilters({
            ...filters,
            properties: [
                ...personProperties,
                { type: PropertyFilterType.Person, key: key, value: null, operator: PropertyOperator.Exact },
            ],
        })
    }

    const onClickCurrentUrl = (): void => {
        const events = filters.events || []
        setFilters({
            ...filters,
            events: [
                ...events,
                {
                    id: '$pageview',
                    name: '$pageview',
                    type: EntityTypes.EVENTS,
                    properties: [
                        {
                            type: PropertyFilterType.Event,
                            key: '$current_url',
                            value: null,
                            operator: PropertyOperator.Exact,
                        },
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
        <div className="space-y-3">
            <div className="space-y-1">
                <PropertyFilters
                    pageKey="session-recordings-simple-$country"
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties]}
                    propertyFilters={personProperties}
                    onChange={(properties) => setFilters({ properties })}
                    allowNew={false}
                    openOnInsert
                />
                <PropertyFilters
                    pageKey="session-recordings-simple-$current_url"
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                    propertyFilters={eventProperties}
                    onChange={(properties) => {
                        setFilters({
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
                    openOnInsert
                />
                <LemonMenu
                    items={[
                        {
                            title: 'Preferred properties',
                            items: items,
                        },
                        {
                            items: [
                                {
                                    label: `${
                                        displayNameProperties.length === 0 ? 'Add' : 'Edit'
                                    } person display properties`,
                                    to: urls.settings('project-product-analytics', 'person-display-name'),
                                },
                            ],
                        },
                    ]}
                >
                    <LemonButton size="small" type="secondary" icon={<IconPlus />}>
                        Add property
                    </LemonButton>
                </LemonMenu>
            </div>
        </div>
    )
}
