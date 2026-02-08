import './PropertyFilters.scss'

import { BindLogic, useActions, useValues } from 'kea'
import isEqual from 'lodash.isequal'
import React, { useEffect, useRef, useState } from 'react'

import { TaxonomicPropertyFilter } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter'
import {
    AllowedProperties,
    ExcludedProperties,
    TaxonomicFilterGroupType,
    TaxonomicFilterProps,
} from 'lib/components/TaxonomicFilter/types'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LogicalRowDivider } from 'scenes/cohorts/CohortFilters/CohortCriteriaRowBuilder'

import { AnyDataNode, DatabaseSchemaField } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, FilterLogicalOperator } from '~/types'

import { FilterRow } from './components/FilterRow'
import { OperatorValueSelectProps } from './components/OperatorValueSelect'
import { propertyFilterLogic } from './propertyFilterLogic'

export interface PropertyFiltersProps {
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
    schemaColumns?: DatabaseSchemaField[]
    dataWarehouseTableName?: string
    logicalRowDivider?: boolean
    orFiltering?: boolean
    propertyGroupType?: FilterLogicalOperator | null
    addText?: string | null
    editable?: boolean
    buttonText?: string
    buttonSize?: 'xsmall' | 'small' | 'medium'
    hasRowOperator?: boolean
    sendAllKeyUpdates?: boolean
    allowNew?: boolean
    openOnInsert?: boolean
    errorMessages?: JSX.Element[] | null
    propertyAllowList?: AllowedProperties
    excludedProperties?: ExcludedProperties
    allowRelativeDateOptions?: boolean
    disabledReason?: string
    exactMatchFeatureFlagCohortOperators?: boolean
    hideBehavioralCohorts?: boolean
    addFilterDocLink?: string
    operatorAllowlist?: OperatorValueSelectProps['operatorAllowlist']
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
    dataWarehouseTableName,
    orFiltering = false,
    logicalRowDivider = false,
    propertyGroupType = null,
    addText = null,
    buttonText = 'Filter',
    editable = true,
    buttonSize,
    hasRowOperator = true,
    sendAllKeyUpdates = false,
    allowNew = true,
    openOnInsert = false,
    errorMessages = null,
    propertyAllowList,
    excludedProperties,
    allowRelativeDateOptions,
    disabledReason = undefined,
    exactMatchFeatureFlagCohortOperators = false,
    hideBehavioralCohorts,
    addFilterDocLink,
    operatorAllowlist,
}: PropertyFiltersProps): JSX.Element {
    const logicProps = { propertyFilters, onChange, pageKey, sendAllKeyUpdates }
    const { filters, filtersWithNew } = useValues(propertyFilterLogic(logicProps))
    const { remove, setFilters, setFilter } = useActions(propertyFilterLogic(logicProps))
    const [allowOpenOnInsert, setAllowOpenOnInsert] = useState<boolean>(false)

    // Update the logic's internal filters when the props change, but only if
    // the content actually changed (not just the reference).
    const prevPropertyFiltersRef = useRef(propertyFilters)
    useEffect(() => {
        if (!isEqual(prevPropertyFiltersRef.current, propertyFilters)) {
            prevPropertyFiltersRef.current = propertyFilters
            setFilters(propertyFilters ?? [])
        }
    }, [propertyFilters, setFilters])

    // Stable keys for filter rows so that deleting a filter doesn't remount siblings.
    const filterKeyCounterRef = useRef(0)
    const filterKeysRef = useRef<number[]>([])

    const displayedFilters = allowNew && editable ? filtersWithNew : filters

    // Grow keys array as filters are added
    while (filterKeysRef.current.length < displayedFilters.length) {
        filterKeysRef.current.push(filterKeyCounterRef.current++)
    }

    const handleRemove = (index: number): void => {
        filterKeysRef.current.splice(index, 1)
        remove(index)
    }

    // do not open on initial render, only open if newly inserted
    useOnMountEffect(() => setAllowOpenOnInsert(true))

    return (
        <div className="PropertyFilters">
            {showNestedArrow && !disablePopover && (
                <div className="PropertyFilters__prefix">
                    <>&#8627;</>
                </div>
            )}
            <div className="PropertyFilters__content max-w-full">
                <BindLogic logic={propertyFilterLogic} props={logicProps}>
                    {displayedFilters.map((item: AnyPropertyFilter, index: number) => {
                        return (
                            <React.Fragment key={filterKeysRef.current[index]}>
                                {logicalRowDivider && index > 0 && index !== filtersWithNew.length - 1 && (
                                    <LogicalRowDivider logicalOperator={FilterLogicalOperator.And} />
                                )}
                                <FilterRow
                                    item={item}
                                    index={index}
                                    totalCount={filtersWithNew.length - 1} // empty state
                                    filters={filtersWithNew}
                                    pageKey={pageKey}
                                    showConditionBadge={showConditionBadge}
                                    disablePopover={disablePopover || orFiltering}
                                    label={buttonText}
                                    size={buttonSize}
                                    onRemove={handleRemove}
                                    orFiltering={orFiltering}
                                    editable={editable}
                                    filterComponent={(onComplete) => (
                                        <TaxonomicPropertyFilter
                                            pageKey={pageKey}
                                            index={index}
                                            filters={filters}
                                            setFilter={setFilter}
                                            onComplete={onComplete}
                                            orFiltering={orFiltering}
                                            taxonomicGroupTypes={taxonomicGroupTypes}
                                            metadataSource={metadataSource}
                                            eventNames={eventNames}
                                            schemaColumns={schemaColumns}
                                            dataWarehouseTableName={dataWarehouseTableName}
                                            propertyGroupType={propertyGroupType}
                                            disablePopover={disablePopover || orFiltering}
                                            addText={addText}
                                            hasRowOperator={hasRowOperator}
                                            propertyAllowList={propertyAllowList}
                                            excludedProperties={excludedProperties}
                                            taxonomicFilterOptionsFromProp={taxonomicFilterOptionsFromProp}
                                            allowRelativeDateOptions={allowRelativeDateOptions}
                                            exactMatchFeatureFlagCohortOperators={exactMatchFeatureFlagCohortOperators}
                                            hideBehavioralCohorts={hideBehavioralCohorts}
                                            size={buttonSize}
                                            addFilterDocLink={addFilterDocLink}
                                            editable={editable}
                                            operatorAllowlist={operatorAllowlist}
                                        />
                                    )}
                                    errorMessage={errorMessages && errorMessages[index]}
                                    openOnInsert={allowOpenOnInsert && openOnInsert}
                                    disabledReason={disabledReason}
                                />
                            </React.Fragment>
                        )
                    })}
                </BindLogic>
            </div>
        </div>
    )
}
