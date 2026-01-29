import 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter.scss'

import { useValues } from 'kea'
import { useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { OperatorValueSelect } from 'lib/components/PropertyFilters/components/OperatorValueSelect'
import {
    PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE,
    taxonomicFilterTypeToPropertyFilterType,
} from 'lib/components/PropertyFilters/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'

import { groupsModel } from '~/models/groupsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import {
    EventsNode,
    EventsQuery,
    HogQLQuery,
    SessionAttributionExplorerQuery,
    SessionsQuery,
    TracesQuery,
} from '~/queries/schema/schema-general'
import { isHogQLQuery, isSessionAttributionExplorerQuery, isSessionsQuery } from '~/queries/utils'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

interface EventPropertyFiltersProps<
    Q extends EventsNode | EventsQuery | HogQLQuery | SessionAttributionExplorerQuery | SessionsQuery | TracesQuery,
> {
    query: Q
    setQuery?: (query: Q) => void
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    allowNew?: boolean
}

let uniqueNode = 0
export function EventPropertyFilters<
    Q extends EventsNode | EventsQuery | HogQLQuery | SessionAttributionExplorerQuery | SessionsQuery | TracesQuery,
>({ query, setQuery, taxonomicGroupTypes, allowNew = true }: EventPropertyFiltersProps<Q>): JSX.Element {
    const [id] = useState(() => uniqueNode++)
    const properties =
        isHogQLQuery(query) || isSessionAttributionExplorerQuery(query)
            ? query.filters?.properties
            : isSessionsQuery(query)
              ? query.eventProperties
              : query.properties
    const eventNames =
        isHogQLQuery(query) || isSessionAttributionExplorerQuery(query)
            ? []
            : 'event' in query && query.event
              ? [query.event]
              : []
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    return !properties || Array.isArray(properties) ? (
        <PropertyFilters
            propertyFilters={properties || []}
            taxonomicGroupTypes={
                taxonomicGroupTypes || [
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.EventFeatureFlags,
                    TaxonomicFilterGroupType.EventMetadata,
                    ...groupsTaxonomicTypes,
                    TaxonomicFilterGroupType.Cohorts,
                    TaxonomicFilterGroupType.Elements,
                    TaxonomicFilterGroupType.HogQLExpression,
                ]
            }
            onChange={(value: AnyPropertyFilter[]) => {
                if (isHogQLQuery(query) || isSessionAttributionExplorerQuery(query)) {
                    setQuery?.({ ...query, filters: { ...query.filters, properties: value } })
                } else if (isSessionsQuery(query)) {
                    setQuery?.({ ...query, eventProperties: value })
                } else {
                    setQuery?.({ ...query, properties: value })
                }
            }}
            pageKey={`EventPropertyFilters.${id}`}
            eventNames={eventNames}
            allowNew={allowNew}
        />
    ) : (
        <div>Error: property groups are not supported.</div>
    )
}

interface AddPropertyFilterButtonProps<
    Q extends EventsNode | EventsQuery | HogQLQuery | SessionAttributionExplorerQuery | SessionsQuery | TracesQuery,
> {
    query: Q
    setQuery?: (query: Q) => void
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
}

export function AddPropertyFilterButton<
    Q extends EventsNode | EventsQuery | HogQLQuery | SessionAttributionExplorerQuery | SessionsQuery | TracesQuery,
>({ query, setQuery, taxonomicGroupTypes }: AddPropertyFilterButtonProps<Q>): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    const [selectedProperty, setSelectedProperty] = useState<{
        key: string
        type: PropertyFilterType
    } | null>(null)

    const properties =
        isHogQLQuery(query) || isSessionAttributionExplorerQuery(query)
            ? query.filters?.properties
            : isSessionsQuery(query)
              ? query.eventProperties
              : query.properties

    const eventNames =
        isHogQLQuery(query) || isSessionAttributionExplorerQuery(query)
            ? []
            : 'event' in query && query.event
              ? [query.event]
              : []

    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const { propertyDefinitionsByType } = useValues(propertyDefinitionsModel)

    const defaultTaxonomicGroupTypes = taxonomicGroupTypes || [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.EventFeatureFlags,
        TaxonomicFilterGroupType.EventMetadata,
        ...groupsTaxonomicTypes,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.Elements,
        TaxonomicFilterGroupType.HogQLExpression,
    ]

    const closeAndReset = (): void => {
        setIsOpen(false)
        setSelectedProperty(null)
    }

    const handleSelectProperty = (group: TaxonomicFilterGroup, value: TaxonomicFilterValue): void => {
        const propertyFilterType = taxonomicFilterTypeToPropertyFilterType(group.type)
        if (propertyFilterType) {
            setSelectedProperty({
                key: String(value),
                type: propertyFilterType,
            })
        }
    }

    const handleOperatorValueChange = (operator: PropertyOperator, value: any): void => {
        if (!selectedProperty) {
            return
        }

        // Create and add the filter
        const currentProperties = (properties || []) as AnyPropertyFilter[]
        const newFilter: AnyPropertyFilter = {
            type: selectedProperty.type,
            key: selectedProperty.key,
            value: value ?? null,
            operator: operator,
        } as AnyPropertyFilter

        const newProperties = [...currentProperties, newFilter]

        if (isHogQLQuery(query) || isSessionAttributionExplorerQuery(query)) {
            setQuery?.({ ...query, filters: { ...query.filters, properties: newProperties } })
        } else if (isSessionsQuery(query)) {
            setQuery?.({ ...query, eventProperties: newProperties })
        } else {
            setQuery?.({ ...query, properties: newProperties })
        }

        // Always close after applying a filter
        requestAnimationFrame(closeAndReset)
    }

    const propertyDefinitions = selectedProperty ? propertyDefinitionsByType(selectedProperty.type) : []

    return (
        <LemonDropdown
            visible={isOpen}
            onVisibilityChange={(visible) => {
                if (visible) {
                    setIsOpen(true)
                } else {
                    closeAndReset()
                }
            }}
            closeOnClickInside={false}
            matchWidth={false}
            overlay={
                selectedProperty ? (
                    <div className="TaxonomicPropertyFilter TaxonomicPropertyFilter--in-dropdown">
                        <div className="TaxonomicPropertyFilter__row TaxonomicPropertyFilter__row--showing-operators TaxonomicPropertyFilter__row--editable">
                            <div className="TaxonomicPropertyFilter__row-items">
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    sideIcon={null}
                                    onClick={() => setSelectedProperty(null)}
                                >
                                    <PropertyKeyInfo
                                        value={selectedProperty.key}
                                        disablePopover
                                        ellipsis
                                        type={
                                            PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE[selectedProperty.type]
                                        }
                                    />
                                </LemonButton>
                                <OperatorValueSelect
                                    propertyDefinitions={propertyDefinitions}
                                    type={selectedProperty.type}
                                    propertyKey={selectedProperty.key}
                                    operator={null}
                                    value={null}
                                    placeholder="Enter value..."
                                    onChange={handleOperatorValueChange}
                                    eventNames={eventNames}
                                    size="small"
                                    editable={true}
                                    startVisible={true}
                                    forceSingleSelect={true}
                                />
                            </div>
                        </div>
                    </div>
                ) : (
                    <TaxonomicFilter
                        groupType={TaxonomicFilterGroupType.EventProperties}
                        onChange={handleSelectProperty}
                        taxonomicGroupTypes={defaultTaxonomicGroupTypes}
                        eventNames={eventNames}
                    />
                )
            }
        >
            <LemonButton type="secondary" size="small" icon={<IconPlusSmall />}>
                Filter
            </LemonButton>
        </LemonDropdown>
    )
}
