import './PropertyFilters.scss'

import { BindLogic, useActions, useValues } from 'kea'
import { TaxonomicPropertyFilter } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter'
import { TaxonomicFilterGroupType, TaxonomicFilterProps } from 'lib/components/TaxonomicFilter/types'
import React, { useEffect, useState } from 'react'
import { LogicalRowDivider } from 'scenes/cohorts/CohortFilters/CohortCriteriaRowBuilder'

import { AnyDataNode, DatabaseSchemaQueryResponseField } from '~/queries/schema'
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
    taxonomicFilterOptionsFromProp?: TaxonomicFilterProps['optionsFromProp']
    metadataSource?: AnyDataNode
    showNestedArrow?: boolean
    eventNames?: string[]
    schemaColumns?: DatabaseSchemaQueryResponseField[]
    logicalRowDivider?: boolean
    orFiltering?: boolean
    propertyGroupType?: FilterLogicalOperator | null
    addText?: string | null
    buttonText?: string
    hasRowOperator?: boolean
    sendAllKeyUpdates?: boolean
    allowNew?: boolean
    openOnInsert?: boolean
    errorMessages?: JSX.Element[] | null
    propertyAllowList?: { [key in TaxonomicFilterGroupType]?: string[] }
    allowRelativeDateOptions?: boolean
}

export function PropertyFilters({
    propertyFilters = null,
    onChange,
    pageKey,
    showConditionBadge = false,
    disablePopover = false, // use bare PropertyFilter without popover
    taxonomicGroupTypes,
    taxonomicFilterOptionsFromProp,
    metadataSource,
    showNestedArrow = false,
    eventNames = [],
    schemaColumns = [],
    orFiltering = false,
    logicalRowDivider = false,
    propertyGroupType = null,
    addText = null,
    buttonText = 'Add filter',
    hasRowOperator = true,
    sendAllKeyUpdates = false,
    allowNew = true,
    openOnInsert = false,
    errorMessages = null,
    propertyAllowList,
    allowRelativeDateOptions,
}: PropertyFiltersProps): JSX.Element {
    const logicProps = { propertyFilters, onChange, pageKey, sendAllKeyUpdates }
    const { filters, filtersWithNew } = useValues(propertyFilterLogic(logicProps))
    const { remove, setFilters } = useActions(propertyFilterLogic(logicProps))
    const [allowOpenOnInsert, setAllowOpenOnInsert] = useState<boolean>(false)

    // Update the logic's internal filters when the props change
    useEffect(() => {
        setFilters(propertyFilters ?? [])
    }, [propertyFilters])

    // do not open on initial render, only open if newly inserted
    useEffect(() => {
        setAllowOpenOnInsert(true)
    }, [])

    return (
        <div className="PropertyFilters">
            {showNestedArrow && !disablePopover && (
                <div className="PropertyFilters__prefix">
                    <>&#8627;</>
                </div>
            )}
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
                                    label={buttonText}
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
                                            metadataSource={metadataSource}
                                            eventNames={eventNames}
                                            schemaColumns={schemaColumns}
                                            propertyGroupType={propertyGroupType}
                                            disablePopover={disablePopover || orFiltering}
                                            addText={addText}
                                            hasRowOperator={hasRowOperator}
                                            selectProps={{
                                                delayBeforeAutoOpen: 150,
                                                placement: pageKey === 'insight-filters' ? 'bottomLeft' : undefined,
                                            }}
                                            propertyAllowList={propertyAllowList}
                                            taxonomicFilterOptionsFromProp={taxonomicFilterOptionsFromProp}
                                            allowRelativeDateOptions={allowRelativeDateOptions}
                                        />
                                    )}
                                    errorMessage={errorMessages && errorMessages[index]}
                                    openOnInsert={allowOpenOnInsert && openOnInsert}
                                />
                            </React.Fragment>
                        )
                    })}
                </BindLogic>
            </div>
        </div>
    )
}
