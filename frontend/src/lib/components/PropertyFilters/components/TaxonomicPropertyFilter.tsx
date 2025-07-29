import './TaxonomicPropertyFilter.scss'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { OperatorValueSelect } from 'lib/components/PropertyFilters/components/OperatorValueSelect'
import { PropertyFilterInternalProps } from 'lib/components/PropertyFilters/types'
import {
    isGroupPropertyFilter,
    isPropertyFilterWithOperator,
    PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE,
    propertyFilterTypeToTaxonomicFilterType,
} from 'lib/components/PropertyFilters/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import { isOperatorMulti, isOperatorRegex } from 'lib/utils'
import { useMemo } from 'react'
import { dataWarehouseJoinsLogic } from 'scenes/data-warehouse/external/dataWarehouseJoinsLogic'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import {
    AnyPropertyFilter,
    FilterLogicalOperator,
    GroupTypeIndex,
    PropertyDefinitionType,
    PropertyFilterType,
} from '~/types'

import { OperandTag } from './OperandTag'
import { taxonomicPropertyFilterLogic } from './taxonomicPropertyFilterLogic'

let uniqueMemoizedIndex = 0
export const DEFAULT_TAXONOMIC_GROUP_TYPES = [
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.EventFeatureFlags,
    TaxonomicFilterGroupType.Cohorts,
    TaxonomicFilterGroupType.Elements,
    TaxonomicFilterGroupType.HogQLExpression,
]

export function TaxonomicPropertyFilter({
    pageKey: pageKeyInput,
    index,
    filters,
    setFilter,
    onComplete,
    disablePopover, // inside a dropdown if this is false
    taxonomicGroupTypes,
    eventNames,
    schemaColumns,
    propertyGroupType,
    orFiltering,
    addText = 'Add filter',
    size = 'medium',
    hasRowOperator,
    metadataSource,
    propertyAllowList,
    excludedProperties,
    taxonomicFilterOptionsFromProp,
    allowRelativeDateOptions,
    exactMatchFeatureFlagCohortOperators,
    hideBehavioralCohorts,
    addFilterDocLink,
    editable = true,
}: PropertyFilterInternalProps): JSX.Element {
    const pageKey = useMemo(() => pageKeyInput || `filter-${uniqueMemoizedIndex++}`, [pageKeyInput])
    const groupTypes = taxonomicGroupTypes || DEFAULT_TAXONOMIC_GROUP_TYPES
    const taxonomicOnChange: (
        group: TaxonomicFilterGroup,
        value: TaxonomicFilterValue,
        item: any,
        originalQuery?: string
    ) => void = (taxonomicGroup, value, item, originalQuery) => {
        selectItem(taxonomicGroup, value, item?.propertyFilterType, item, originalQuery)
        if (taxonomicGroup.type === TaxonomicFilterGroupType.HogQLExpression) {
            onComplete?.()
        }
    }

    const logic = taxonomicPropertyFilterLogic({
        pageKey,
        filters,
        setFilter,
        filterIndex: index,
        taxonomicGroupTypes: groupTypes,
        taxonomicOnChange,
        eventNames,
        propertyAllowList,
        excludedProperties,
    })
    const { filter, dropdownOpen, activeTaxonomicGroup } = useValues(logic)
    const { openDropdown, closeDropdown, selectItem } = useActions(logic)
    const valuePresent = filter?.type === 'cohort' || !!filter?.key
    const showInitialSearchInline =
        !disablePopover &&
        ((!filter?.type && (!filter || !(filter as any)?.key)) || filter?.type === PropertyFilterType.HogQL)
    const showOperatorValueSelect =
        filter?.type &&
        filter?.key &&
        !(filter?.type === PropertyFilterType.HogQL) &&
        // If we're in a feature flag, we don't want to show operators for cohorts because
        // we don't support any cohort matching operators other than "in"
        // See https://github.com/PostHog/posthog/pull/25149/
        !(filter?.type === PropertyFilterType.Cohort && exactMatchFeatureFlagCohortOperators)
    const placeOperatorValueSelectOnLeft = filter?.type && filter?.key && filter?.type === PropertyFilterType.Cohort

    const { propertyDefinitionsByType } = useValues(propertyDefinitionsModel)
    const { columnsJoinedToPersons } = useValues(dataWarehouseJoinsLogic)

    // We don't support array filter values here. Multiple-cohort only supported in TaxonomicBreakdownFilter.
    // This is mostly to make TypeScript happy.
    const cohortOrOtherValue =
        filter?.type === 'cohort' ? (!Array.isArray(filter?.value) && filter?.value) || undefined : filter?.key

    // Get the base property type, defaulting to Event if not specified
    const basePropertyType = filter?.type || PropertyDefinitionType.Event

    // Get the group type index if this is a group property filter
    const groupTypeIndex = isGroupPropertyFilter(filter) ? filter?.group_type_index : undefined

    // For data warehouse person properties, use columnsJoinedToPersons, otherwise use property definitions
    const propertyDefinitions =
        filter?.type === PropertyFilterType.DataWarehousePersonProperty
            ? columnsJoinedToPersons
            : propertyDefinitionsByType(basePropertyType, groupTypeIndex)

    const taxonomicFilter = (
        <TaxonomicFilter
            groupType={filter ? propertyFilterTypeToTaxonomicFilterType(filter) : undefined}
            value={cohortOrOtherValue}
            onChange={taxonomicOnChange}
            taxonomicGroupTypes={groupTypes}
            metadataSource={metadataSource}
            eventNames={eventNames}
            schemaColumns={schemaColumns}
            propertyAllowList={propertyAllowList}
            excludedProperties={excludedProperties}
            optionsFromProp={taxonomicFilterOptionsFromProp}
            hideBehavioralCohorts={hideBehavioralCohorts}
        />
    )

    const operatorValueSelect = (
        <OperatorValueSelect
            propertyDefinitions={propertyDefinitions}
            size={size}
            editable={editable}
            type={filter?.type}
            propertyKey={filter?.key}
            operator={isPropertyFilterWithOperator(filter) ? filter.operator : null}
            value={filter?.value}
            placeholder="Enter value..."
            endpoint={filter?.key && activeTaxonomicGroup?.valuesEndpoint?.(filter.key)}
            eventNames={eventNames}
            addRelativeDateTimeOptions={allowRelativeDateOptions}
            onChange={(newOperator, newValue) => {
                if (filter?.key && filter?.type) {
                    setFilter(index, {
                        key: filter?.key,
                        value: newValue || null,
                        operator: newOperator,
                        type: filter?.type,
                        label: filter?.label,
                        ...(isGroupPropertyFilter(filter) ? { group_type_index: filter.group_type_index } : {}),
                        ...(filter.type === PropertyFilterType.Cohort ? { cohort_name: filter.cohort_name } : {}),
                    } as AnyPropertyFilter)
                }
                if (newOperator && newValue && !isOperatorMulti(newOperator) && !isOperatorRegex(newOperator)) {
                    onComplete()
                }
            }}
            groupTypeIndex={
                isGroupPropertyFilter(filter) && typeof filter?.group_type_index === 'number'
                    ? (filter?.group_type_index as GroupTypeIndex)
                    : undefined
            }
        />
    )

    const filterContent =
        filter?.type === 'cohort'
            ? filter.cohort_name || `Cohort #${filter?.value}`
            : filter?.type === PropertyFilterType.EventMetadata && filter?.key?.startsWith('$group_')
            ? filter.label || `Group ${filter?.value}`
            : filter?.key && (
                  <PropertyKeyInfo
                      value={filter.key}
                      disablePopover
                      ellipsis
                      type={PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE[filter.type]}
                  />
              )

    return (
        <div
            className={clsx('TaxonomicPropertyFilter', {
                'TaxonomicPropertyFilter--in-dropdown': !showInitialSearchInline && !disablePopover,
            })}
        >
            {showInitialSearchInline ? (
                taxonomicFilter
            ) : (
                <div
                    className={clsx('TaxonomicPropertyFilter__row', {
                        'TaxonomicPropertyFilter__row--or-filtering': orFiltering,
                        'TaxonomicPropertyFilter__row--showing-operators': showOperatorValueSelect,
                        'TaxonomicPropertyFilter__row--editable': editable,
                    })}
                >
                    {hasRowOperator && (
                        <div className="TaxonomicPropertyFilter__row-operator">
                            {orFiltering ? (
                                <>
                                    {propertyGroupType && index !== 0 && filter?.key && (
                                        <div className="flex items-center">
                                            {propertyGroupType === FilterLogicalOperator.And ? (
                                                <OperandTag operand="and" />
                                            ) : (
                                                <OperandTag operand="or" />
                                            )}
                                        </div>
                                    )}
                                </>
                            ) : (
                                <div className="flex items-center gap-1">
                                    {index === 0 ? (
                                        <>
                                            <span className="TaxonomicPropertyFilter__row-arrow">&#8627;</span>
                                            <span>where</span>
                                        </>
                                    ) : (
                                        <OperandTag operand="and" />
                                    )}
                                </div>
                            )}
                        </div>
                    )}
                    <div className="TaxonomicPropertyFilter__row-items">
                        {showOperatorValueSelect && placeOperatorValueSelectOnLeft && operatorValueSelect}
                        {editable ? (
                            <LemonDropdown
                                overlay={taxonomicFilter}
                                placement="bottom-start"
                                visible={dropdownOpen}
                                onClickOutside={closeDropdown}
                            >
                                <LemonButton
                                    type="secondary"
                                    icon={!valuePresent ? <IconPlusSmall /> : undefined}
                                    data-attr={'property-select-toggle-' + index}
                                    sideIcon={null} // The null sideIcon is here on purpose - it prevents the dropdown caret
                                    onClick={() => (dropdownOpen ? closeDropdown() : openDropdown())}
                                    size={size}
                                    tooltipDocLink={addFilterDocLink}
                                >
                                    {filterContent ?? (addText || 'Add filter')}
                                </LemonButton>
                            </LemonDropdown>
                        ) : (
                            filterContent
                        )}
                        {showOperatorValueSelect && !placeOperatorValueSelectOnLeft && operatorValueSelect}
                    </div>
                </div>
            )}
        </div>
    )
}
