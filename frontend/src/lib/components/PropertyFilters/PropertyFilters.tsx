import './PropertyFilters.scss'

import { BindLogic, useActions, useValues } from 'kea'
import { TaxonomicPropertyFilter } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import React, { useEffect } from 'react'
import { LogicalRowDivider } from 'scenes/cohorts/CohortFilters/CohortCriteriaRowBuilder'

import { AnyPropertyFilter, FilterLogicalOperator } from '~/types'

import { FilterRow } from './components/FilterRow'
import { propertyFilterLogic } from './propertyFilterLogic'

interface PropertyFiltersProps {
    endpoint?: string | null
    propertyFilters?: AnyPropertyFilter[] | null
    onChange: (filters: AnyPropertyFilter[]) => void
    pageKey: string
    showConditionBadge?: boolean
    disablePopover?: boolean
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    hogQLTable?: string
    showNestedArrow?: boolean
    eventNames?: string[]
    logicalRowDivider?: boolean
    orFiltering?: boolean
    propertyGroupType?: FilterLogicalOperator | null
    addText?: string | null
    hasRowOperator?: boolean
    sendAllKeyUpdates?: boolean
    allowNew?: boolean
    errorMessages?: JSX.Element[] | null
    propertyAllowList?: { [key in TaxonomicFilterGroupType]?: string[] }
}

export function PropertyFilters({
    propertyFilters = null,
    onChange,
    pageKey,
    showConditionBadge = false,
    disablePopover = false, // use bare PropertyFilter without popover
    taxonomicGroupTypes,
    hogQLTable,
    showNestedArrow = false,
    eventNames = [],
    orFiltering = false,
    logicalRowDivider = false,
    propertyGroupType = null,
    addText = null,
    hasRowOperator = true,
    sendAllKeyUpdates = false,
    allowNew = true,
    errorMessages = null,
    propertyAllowList,
}: PropertyFiltersProps): JSX.Element {
    const logicProps = { propertyFilters, onChange, pageKey, sendAllKeyUpdates }
    const { filters, filtersWithNew } = useValues(propertyFilterLogic(logicProps))
    const { remove, setFilters } = useActions(propertyFilterLogic(logicProps))

    // Update the logic's internal filters when the props change
    useEffect(() => {
        setFilters(propertyFilters ?? [])
    }, [propertyFilters])

    return (
        <div className="PropertyFilters">
            {showNestedArrow && !disablePopover && <div className="PropertyFilters__prefix">{<>&#8627;</>}</div>}
            <div className="PropertyFilters__content">
                <BindLogic logic={propertyFilterLogic} props={logicProps}>
                    {(allowNew ? filtersWithNew : filters).map((item: AnyPropertyFilter, index: number) => {
                        return (
                            <React.Fragment key={index}>
                                {logicalRowDivider && index > 0 && index !== filtersWithNew.length - 1 && (
                                    <LogicalRowDivider logicalOperator={FilterLogicalOperator.And} />
                                )}
                                <FilterRow
                                    key={index}
                                    item={item}
                                    index={index}
                                    totalCount={filtersWithNew.length - 1} // empty state
                                    filters={filtersWithNew}
                                    pageKey={pageKey}
                                    showConditionBadge={showConditionBadge}
                                    disablePopover={disablePopover || orFiltering}
                                    label={'Add filter'}
                                    onRemove={remove}
                                    orFiltering={orFiltering}
                                    filterComponent={(onComplete) => (
                                        <TaxonomicPropertyFilter
                                            key={index}
                                            pageKey={pageKey}
                                            index={index}
                                            onComplete={onComplete}
                                            orFiltering={orFiltering}
                                            taxonomicGroupTypes={taxonomicGroupTypes}
                                            hogQLTable={hogQLTable}
                                            eventNames={eventNames}
                                            propertyGroupType={propertyGroupType}
                                            disablePopover={disablePopover || orFiltering}
                                            addText={addText}
                                            hasRowOperator={hasRowOperator}
                                            selectProps={{
                                                delayBeforeAutoOpen: 150,
                                                placement: pageKey === 'insight-filters' ? 'bottomLeft' : undefined,
                                            }}
                                            propertyAllowList={propertyAllowList}
                                        />
                                    )}
                                    errorMessage={errorMessages && errorMessages[index]}
                                />
                            </React.Fragment>
                        )
                    })}
                </BindLogic>
            </div>
        </div>
    )
}
