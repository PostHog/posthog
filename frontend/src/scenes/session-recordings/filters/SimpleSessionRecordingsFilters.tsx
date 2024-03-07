import { IconGear, IconTrash } from '@posthog/icons'
import { LemonButton, LemonMenu, Popover } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useMemo, useRef, useState } from 'react'

import { EntityTypes, EventPropertyFilter, PropertyFilterType, PropertyOperator, RecordingFilters } from '~/types'

import { playerSettingsLogic } from '../player/playerSettingsLogic'

export const SimpleSessionRecordingsFilters = ({
    filters,
    setFilters,
}: {
    filters: RecordingFilters
    setFilters: (filters: RecordingFilters) => void
}): JSX.Element => {
    const { quickFilterProperties } = useValues(playerSettingsLogic)
    const { setQuickFilterProperties } = useActions(playerSettingsLogic)
    const [showPropertySelector, setShowPropertySelector] = useState<boolean>(false)
    const buttonRef = useRef<HTMLButtonElement>(null)

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

    const defaultItems = useMemo(() => {
        const eventKeys = eventProperties.map((p: EventPropertyFilter) => p.key)

        return [
            !eventKeys.includes('$current_url') && {
                label: <PropertyKeyInfo disablePopover disableIcon value="$current_url" />,
                key: '$current_url',
                onClick: onClickCurrentUrl,
            },
        ].filter(Boolean)
    }, [eventProperties])

    const personPropertyItems = useMemo(() => {
        const personKeys = personProperties.map((p) => p.key)

        return quickFilterProperties
            .map((property) => {
                return (
                    !personKeys.includes(property) && {
                        label: <PropertyKeyInfo disablePopover disableIcon value={property} />,
                        key: property,
                        onClick: () => onClickPersonProperty(property),
                    }
                )
            })
            .filter(Boolean)
    }, [quickFilterProperties, personProperties])

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
                <Popover
                    visible={showPropertySelector}
                    onClickOutside={() => setShowPropertySelector(false)}
                    overlay={
                        <Configuration
                            properties={quickFilterProperties}
                            onChange={(value) => {
                                setQuickFilterProperties(value)
                            }}
                        />
                    }
                    referenceElement={buttonRef.current}
                    placement="right-start"
                >
                    <LemonMenu
                        items={[
                            defaultItems.length > 0 && { items: defaultItems },
                            personPropertyItems.length > 0 && {
                                title: 'Person properties',
                                items: personPropertyItems,
                            },
                        ]}
                        onVisibilityChange={() => setShowPropertySelector(false)}
                    >
                        <LemonButton
                            ref={buttonRef}
                            size="small"
                            type="secondary"
                            sideAction={{
                                icon: <IconGear />,
                                tooltip: 'Edit properties',
                                onClick: () => setShowPropertySelector(true),
                            }}
                        >
                            Choose quick filter
                        </LemonButton>
                    </LemonMenu>
                </Popover>
            </div>
        </div>
    )
}

const Configuration = ({
    properties,
    onChange,
}: {
    properties: string[]
    onChange: (properties: string[]) => void
}): JSX.Element => {
    const [showPropertySelector, setShowPropertySelector] = useState<boolean>(false)

    return (
        <div className="font-medium">
            {properties.map((property) => (
                <div className="flex items-center p-1 gap-2" key={property}>
                    <span className="flex-1">
                        <PropertyKeyInfo value={property} />
                    </span>
                    <LemonButton
                        size="xsmall"
                        status="danger"
                        icon={<IconTrash />}
                        onClick={() => {
                            const newProperties = properties.filter((p) => p != property)
                            onChange(newProperties)
                        }}
                    />
                </div>
            ))}
            <Popover
                visible={showPropertySelector}
                onClickOutside={() => setShowPropertySelector(false)}
                placement="right-start"
                overlay={
                    <TaxonomicFilter
                        onChange={(_, value) => {
                            properties.push(value as string)
                            onChange([...properties])
                            setShowPropertySelector(false)
                        }}
                        taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties]}
                        excludedProperties={{ [TaxonomicFilterGroupType.PersonProperties]: properties }}
                    />
                }
            >
                <LemonButton onClick={() => setShowPropertySelector(!showPropertySelector)} fullWidth>
                    Add person properties
                </LemonButton>
            </Popover>
        </div>
    )
}
