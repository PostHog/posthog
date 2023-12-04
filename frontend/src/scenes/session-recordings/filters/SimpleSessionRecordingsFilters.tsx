import { urls } from '@posthog/apps-common'
import { LemonButton, Link } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { TaxonomicPropertyFilter } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter'
import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { PropertyFilterLogicProps } from 'lib/components/PropertyFilters/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconPlus } from 'lib/lemon-ui/icons'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { useMemo, useState } from 'react'
import { teamLogic } from 'scenes/teamLogic'

import {
    AnyPropertyFilter,
    EntityTypes,
    FilterType,
    PropertyFilterType,
    PropertyOperator,
    RecordingFilters,
} from '~/types'

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

    const displayNameProperties = useMemo(() => currentTeam?.person_display_name_properties ?? [], [currentTeam])

    const personPropertyOptions = useMemo(() => {
        const properties = [{ label: 'Country', key: '$geoip_country_name' }]
        return properties.concat(
            displayNameProperties.slice(0, 2).map((property) => {
                return { label: property, key: property }
            })
        )
    }, [displayNameProperties])

    const pageviewEvent = localFilters.events?.find((event) => event.id === '$pageview')

    const personProperties = filters.properties || []
    const eventProperties = pageviewEvent?.properties || []

    return (
        <div className="space-y-2">
            <div className="flex flex-wrap gap-1">
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
                {displayNameProperties.length === 0 && (
                    <Link to={urls.settings('project', 'person-display-name')}>
                        <LemonButton type="tertiary" size="small" className="whitespace-nowrap" icon={<IconPlus />}>
                            Add person properties
                        </LemonButton>
                    </Link>
                )}
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
                    data-attr={'simple-session-recordings-filter'}
                    data-ph-capture-attribute-simple-filter-property-key={propertyKey}
                    onClick={() => handleVisibleChange(true)}
                    className="new-prop-filter"
                    type="secondary"
                    size="small"
                    disabledReason={disabled && 'Add more values using your existing filter.'}
                    sideIcon={null}
                >
                    {label}
                </LemonButton>
            </Popover>
        </BindLogic>
    )
}
