import './PropertyFilters.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import React, { useState } from 'react'

import { BehavioralPropertyFilterRow } from 'lib/components/PropertyFilters/components/BehavioralPropertyFilterRow'
import { FILTER_ROW_FRAME_CLASSES } from 'lib/components/PropertyFilters/components/filterRowFrame'
import { PropertyFilterRowOperator } from 'lib/components/PropertyFilters/components/PropertyFilterRowOperator'
import { TaxonomicPropertyFilter } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter'
import { isBehavioralPropertyFilter } from 'lib/components/PropertyFilters/utils'
import {
    AllowedProperties,
    ExcludedOperators,
    ExcludedProperties,
    SelectingKeyOnly,
    TaxonomicFilterGroupType,
    TaxonomicFilterProps,
} from 'lib/components/TaxonomicFilter/types'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LogicalRowDivider } from 'scenes/cohorts/CohortFilters/CohortCriteriaRowBuilder'

import { AnyDataNode, DatabaseSchemaField } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, FilterLogicalOperator, PropertyDefinition } from '~/types'

import { FilterRow } from './components/FilterRow'
import { OperatorValueSelectProps } from './components/OperatorValueSelect'
import { propertyFilterLogic } from './propertyFilterLogic'
import { PropertyFilterInternalProps } from './types'

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
    buttonClassName?: string
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
    excludedOperators?: ExcludedOperators
    selectingKeyOnly?: SelectingKeyOnly
    hideBehavioralCohorts?: boolean
    addFilterDocLink?: string
    operatorAllowlist?: OperatorValueSelectProps['operatorAllowlist']
    hogQLGlobals?: Record<string, any>
    /**
     * `'input'` renders the replay-style input-box add-filter trigger; `'button'`
     * (the default) renders a button. Only has an effect on the rebuild menu
     * (`TAXONOMIC_FILTER_MENU_REBUILD`).
     */
    triggerVariant?: 'button' | 'input'
    staticValueOptions?: PropertyFilterInternalProps['staticValueOptions']
    /** Override inferred property definitions for contexts where one event key is polymorphic. */
    propertyDefinitionsOverride?: PropertyDefinition[]
    /** Keep the selected key fixed while leaving its operator and value editable. */
    propertyKeyEditable?: boolean
    singleLine?: boolean
    showRemoveButton?: boolean
    /** Rendered after the last row. Receives a callback that appends to this filter's own bound
     * logic, so the caller doesn't have to rebuild the list from possibly-stale props. */
    addFilterSuffix?: ((addFilter: (property: AnyPropertyFilter) => void) => JSX.Element) | null
    addFilterDivider?: boolean
    framedRows?: boolean
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
    buttonClassName = '',
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
    excludedOperators,
    selectingKeyOnly,
    hideBehavioralCohorts,
    addFilterDocLink,
    operatorAllowlist,
    hogQLGlobals,
    triggerVariant = 'button',
    staticValueOptions,
    propertyDefinitionsOverride,
    propertyKeyEditable,
    singleLine,
    showRemoveButton = true,
    addFilterSuffix,
    addFilterDivider = false,
    framedRows = false,
}: PropertyFiltersProps): JSX.Element {
    const logicProps = { propertyFilters, onChange, pageKey, sendAllKeyUpdates }
    const { filters, filtersWithNew, filterIds, filterIdsWithNew } = useValues(propertyFilterLogic(logicProps))
    const { remove, setFilter } = useActions(propertyFilterLogic(logicProps))
    const [allowOpenOnInsert, setAllowOpenOnInsert] = useState<boolean>(false)

    const showNewFilterRow = allowNew && editable
    const displayedFilters = showNewFilterRow ? filtersWithNew : filters
    const displayedFilterIds = showNewFilterRow ? filterIdsWithNew : filterIds

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
                            <React.Fragment key={displayedFilterIds[index]}>
                                {logicalRowDivider && index > 0 && index !== displayedFilters.length - 1 && (
                                    <LogicalRowDivider
                                        logicalOperator={propertyGroupType ?? FilterLogicalOperator.And}
                                    />
                                )}
                                {addFilterDivider &&
                                    showNewFilterRow &&
                                    index === displayedFilters.length - 1 &&
                                    filters.length > 0 && <LemonDivider className="my-1 w-full" />}
                                <FilterRow
                                    item={item}
                                    index={index}
                                    totalCount={displayedFilters.length - 1} // empty state
                                    filters={displayedFilters}
                                    pageKey={pageKey}
                                    showConditionBadge={showConditionBadge}
                                    disablePopover={disablePopover || orFiltering}
                                    label={buttonText}
                                    labelClassName={buttonClassName}
                                    size={buttonSize}
                                    onRemove={remove}
                                    showRemoveButton={showRemoveButton}
                                    orFiltering={orFiltering}
                                    editable={editable}
                                    filterComponent={(onComplete) =>
                                        isBehavioralPropertyFilter(item) ? (
                                            <div className="TaxonomicPropertyFilter__row w-full min-w-0">
                                                {hasRowOperator && (
                                                    <PropertyFilterRowOperator
                                                        index={index}
                                                        orFiltering={orFiltering}
                                                        propertyGroupType={propertyGroupType}
                                                        hasKey={!!item.key}
                                                    />
                                                )}
                                                <div
                                                    className={clsx(
                                                        'TaxonomicPropertyFilter__row-items',
                                                        framedRows && FILTER_ROW_FRAME_CLASSES
                                                    )}
                                                >
                                                    <BehavioralPropertyFilterRow
                                                        filter={item}
                                                        onChange={(filter) => setFilter(index, filter)}
                                                        editable={editable}
                                                        size={buttonSize}
                                                    />
                                                </div>
                                            </div>
                                        ) : (
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
                                                excludedOperators={excludedOperators}
                                                selectingKeyOnly={selectingKeyOnly}
                                                hideBehavioralCohorts={hideBehavioralCohorts}
                                                size={buttonSize}
                                                addFilterDocLink={addFilterDocLink}
                                                editable={editable}
                                                operatorAllowlist={operatorAllowlist}
                                                hogQLGlobals={hogQLGlobals}
                                                triggerVariant={triggerVariant}
                                                staticValueOptions={staticValueOptions}
                                                propertyDefinitionsOverride={propertyDefinitionsOverride}
                                                propertyKeyEditable={propertyKeyEditable}
                                                singleLine={singleLine}
                                                framedRows={framedRows}
                                            />
                                        )
                                    }
                                    errorMessage={errorMessages && errorMessages[index]}
                                    openOnInsert={allowOpenOnInsert && openOnInsert}
                                    disabledReason={disabledReason}
                                    suffix={
                                        showNewFilterRow && index === displayedFilters.length - 1 && addFilterSuffix
                                            ? addFilterSuffix((property) => setFilter(filters.length, property))
                                            : null
                                    }
                                />
                            </React.Fragment>
                        )
                    })}
                </BindLogic>
            </div>
        </div>
    )
}
