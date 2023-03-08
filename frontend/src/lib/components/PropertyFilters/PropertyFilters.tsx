import React, { CSSProperties, useEffect } from 'react'
import { useValues, BindLogic, useActions } from 'kea'
import { propertyFilterLogic } from './propertyFilterLogic'
import { FilterRow } from './components/FilterRow'
import { AnyPropertyFilter, FilterLogicalOperator } from '~/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPropertyFilter } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter'
import './PropertyFilters.scss'
import { LogicalRowDivider } from 'scenes/cohorts/CohortFilters/CohortCriteriaRowBuilder'

interface PropertyFiltersProps {
    endpoint?: string | null
    propertyFilters?: AnyPropertyFilter[] | null
    onChange: (filters: AnyPropertyFilter[]) => void
    pageKey: string
    showConditionBadge?: boolean
    disablePopover?: boolean
    style?: CSSProperties
    taxonomicGroupTypes?: TaxonomicFilterGroupType[]
    showNestedArrow?: boolean
    eventNames?: string[]
    logicalRowDivider?: boolean
    orFiltering?: boolean
    propertyGroupType?: FilterLogicalOperator | null
    addButton?: JSX.Element | null
    hasRowOperator?: boolean
    sendAllKeyUpdates?: boolean
    errorMessages?: JSX.Element[] | null
}

export function PropertyFilters({
    propertyFilters = null,
    onChange,
    pageKey,
    showConditionBadge = false,
    disablePopover = false, // use bare PropertyFilter without popover
    taxonomicGroupTypes,
    style = {},
    showNestedArrow = false,
    eventNames = [],
    orFiltering = false,
    logicalRowDivider = false,
    propertyGroupType = null,
    addButton = null,
    hasRowOperator = true,
    sendAllKeyUpdates = false,
    errorMessages = null,
}: PropertyFiltersProps): JSX.Element {
    const logicProps = { propertyFilters, onChange, pageKey, sendAllKeyUpdates }
    const { filtersWithNew } = useValues(propertyFilterLogic(logicProps))
    const { remove, setFilters } = useActions(propertyFilterLogic(logicProps))

    // Update the logic's internal filters when the props change
    useEffect(() => {
        setFilters(propertyFilters ?? [])
    }, [propertyFilters])

    return (
        <div className="PropertyFilters" style={style}>
            {showNestedArrow && !disablePopover && <div className="PropertyFilters-prefix">{<>&#8627;</>}</div>}
            <div className="PropertyFilters-content">
                <BindLogic logic={propertyFilterLogic} props={logicProps}>
                    {filtersWithNew.map((item: AnyPropertyFilter, index: number) => {
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
                                            eventNames={eventNames}
                                            propertyGroupType={propertyGroupType}
                                            disablePopover={disablePopover || orFiltering}
                                            addButton={addButton}
                                            hasRowOperator={hasRowOperator}
                                            selectProps={{
                                                delayBeforeAutoOpen: 150,
                                                placement: pageKey === 'insight-filters' ? 'bottomLeft' : undefined,
                                            }}
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
