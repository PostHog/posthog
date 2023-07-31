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
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonButton } from '@posthog/lemon-ui'

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

    const pageKey = 'session-recordings'

    const rawOnChange = (newProperties: AnyPropertyFilter[]): void => {
        if (newProperties[0].key === '$current_url') {
            const events = filters.events || []
            setLocalFilters({
                ...filters,
                events: [
                    ...events,
                    {
                        id: '$pageview',
                        name: '$pageview',
                        type: EntityTypes.EVENTS,
                        properties: newProperties,
                    },
                ],
            })
        } else {
            const properties = filters.properties || []
            setFilters({ ...filters, properties: [...properties, ...newProperties] })
        }
    }

    const defaultProperties = useMemo(() => {
        const displayNameProperties = currentTeam?.person_display_name_properties ?? []
        return displayNameProperties
            .map((property) => {
                return { label: property, key: property, type: PropertyFilterType.Person }
            })
            .concat([
                { label: 'Country', key: '$geoip_country_name', type: PropertyFilterType.Person },
                { label: 'URL', key: '$current_url', type: PropertyFilterType.Event },
            ])
    }, [currentTeam])

    const pageviewEvents = (localFilters.events || []).filter((event) => event.key != '$pageview')

    return (
        <div className="space-y-2">
            <PropertyFilters
                pageKey={pageKey}
                taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties]}
                propertyFilters={filters.properties}
                onChange={(properties) => {
                    setFilters({ properties })
                }}
                allowNew={false}
            />
            <PropertyFilters
                pageKey={pageKey}
                taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                propertyFilters={pageviewEvents.flatMap((event) => event.properties)}
                onChange={() => {
                    // setLocalFilters({events})
                }}
                allowNew={false}
            />

            <div className="flex space-x-1">
                {defaultProperties.map(({ label, key, type }) => (
                    <SimpleSessionRecordingsFiltersInserter
                        key={key}
                        type={type}
                        propertyKey={key}
                        label={label}
                        pageKey={`${pageKey}-${key}`}
                        onChange={rawOnChange}
                    />
                ))}
            </div>
        </div>
    )
}

const SimpleSessionRecordingsFiltersInserter = ({
    propertyKey,
    type,
    label,
    pageKey,
    onChange,
}: {
    propertyKey: string
    type: PropertyFilterType
    label: string
    pageKey: string
    onChange: (properties: AnyPropertyFilter[]) => void
}): JSX.Element => {
    const [open, setOpen] = useState(false)

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
                    data-attr={'new-prop-filter-' + pageKey}
                    type="secondary"
                    size="small"
                    sideIcon={null}
                >
                    {label}
                </LemonButton>
            </Popover>
        </BindLogic>
    )
}
