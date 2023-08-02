import {
    AnyPropertyFilter,
    EntityTypes,
    FilterType,
    PropertyFilterType,
    PropertyOperator,
    RecordingFilters,
} from '~/types'
import { useMemo, useState } from 'react'
import { BindLogic, useActions, useValues } from 'kea'
import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'
import { TaxonomicPropertyFilter } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter'
import { PropertyFilterLogicProps } from 'lib/components/PropertyFilters/types'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { teamLogic } from 'scenes/teamLogic'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonButton } from '@posthog/lemon-ui'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'

export const SimpleSessionRecordingsFilters = ({
    filters,
    setFilters,
    localFilters,
    setLocalFilters,
}: {
    filters: RecordingFilters
    setFilters: (filters: RecordingFilters) => void
    localFilters: FilterType
    setLocalFilters: (localFilters: FilterType) => void
}): JSX.Element => {
    const { currentTeam } = useValues(teamLogic)

    const personPropertyOptions = useMemo(() => {
        const properties = [{ label: 'Country', key: '$geoip_country_name' }]
        const displayNameProperties = currentTeam?.person_display_name_properties ?? []
        return properties.concat(
            displayNameProperties.slice(0, 2).map((property) => {
                return { label: property, key: property }
            })
        )
    }, [currentTeam])

    const pageviewEvent = localFilters.events?.find((event) => event.id === '$pageview')

    const personProperties = filters.properties || []
    const eventProperties = pageviewEvent?.properties || []

    return (
        <div className="space-y-2">
            <div className="flex space-x-1">
                {personPropertyOptions.map(({ label, key }) => (
                    <SimpleSessionRecordingsFiltersInserter
                        key={key}
                        type={PropertyFilterType.Person}
                        propertyKey={key}
                        label={label}
                        disabled={personProperties.some((property) => property.key === key)}
                        onChange={(newProperties) => {
                            const properties = filters.properties || []
                            setFilters({ ...filters, properties: [...properties, ...newProperties] })
                        }}
                    />
                ))}
                <SimpleSessionRecordingsFiltersInserter
                    type={PropertyFilterType.Event}
                    propertyKey="$current_url"
                    label="URL"
                    disabled={!!pageviewEvent}
                    onChange={(properties) => {
                        const events = filters.events || []
                        setLocalFilters({
                            ...filters,
                            events: [
                                ...events,
                                {
                                    id: '$pageview',
                                    name: '$pageview',
                                    type: EntityTypes.EVENTS,
                                    properties: properties,
                                },
                            ],
                        })
                    }}
                />
            </div>

            {personProperties && (
                <PropertyFilters
                    pageKey={'session-recordings'}
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties]}
                    propertyFilters={personProperties}
                    onChange={(properties) => setFilters({ properties })}
                    allowNew={false}
                />
            )}
            {pageviewEvent && (
                <PropertyFilters
                    pageKey={`session-recordings-$current_url`}
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
            )}
        </div>
    )
}

const SimpleSessionRecordingsFiltersInserter = ({
    propertyKey,
    type,
    label,
    disabled,
    onChange,
}: {
    propertyKey: string
    type: PropertyFilterType.Event | PropertyFilterType.Person
    label: string
    disabled: boolean
    onChange: (properties: AnyPropertyFilter[]) => void
}): JSX.Element => {
    const [open, setOpen] = useState(false)

    const pageKey = `session-recordings-inserter-${propertyKey}`

    const logicProps: PropertyFilterLogicProps = {
        propertyFilters: [{ type: type, key: propertyKey, operator: PropertyOperator.Exact }],
        onChange,
        pageKey: pageKey,
        sendAllKeyUpdates: false,
    }

    const { setFilters } = useActions(propertyFilterLogic(logicProps))

    const handleVisibleChange = (visible: boolean): void => {
        if (!visible) {
            setFilters([{ type: type, key: propertyKey, operator: PropertyOperator.Exact }])
        }

        setOpen(visible)
    }

    return (
        <BindLogic logic={propertyFilterLogic} props={logicProps}>
            <Popover
                className={'filter-row-popover'}
                visible={open}
                onClickOutside={() => handleVisibleChange(false)}
                overlay={
                    <TaxonomicPropertyFilter
                        pageKey={pageKey}
                        index={0}
                        onComplete={() => handleVisibleChange(false)}
                        orFiltering={false}
                        taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties]}
                        propertyGroupType={null}
                        disablePopover={false}
                        selectProps={{}}
                    />
                }
            >
                <LemonButton
                    onClick={() => handleVisibleChange(true)}
                    className="new-prop-filter"
                    type="secondary"
                    size="small"
                    disabledReason={disabled && 'Add more properties using your existing filter.'}
                    sideIcon={null}
                >
                    {label}
                </LemonButton>
            </Popover>
        </BindLogic>
    )
}
