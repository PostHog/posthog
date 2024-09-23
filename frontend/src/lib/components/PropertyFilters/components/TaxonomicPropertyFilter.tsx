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

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { AnyPropertyFilter, FilterLogicalOperator, PropertyDefinitionType, PropertyFilterType } from '~/types'

import { OperandTag } from './OperandTag'
import { taxonomicPropertyFilterLogic } from './taxonomicPropertyFilterLogic'

let uniqueMemoizedIndex = 0

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
    hasRowOperator,
    metadataSource,
    propertyAllowList,
    taxonomicFilterOptionsFromProp,
    allowRelativeDateOptions,
    restrictFeatureFlagCohortOperators,
}: PropertyFilterInternalProps): JSX.Element {
    const pageKey = useMemo(() => pageKeyInput || `filter-${uniqueMemoizedIndex++}`, [pageKeyInput])
    const groupTypes = taxonomicGroupTypes || [
        TaxonomicFilterGroupType.EventProperties,
        TaxonomicFilterGroupType.PersonProperties,
        TaxonomicFilterGroupType.EventFeatureFlags,
        TaxonomicFilterGroupType.Cohorts,
        TaxonomicFilterGroupType.Elements,
        TaxonomicFilterGroupType.HogQLExpression,
    ]
    const taxonomicOnChange: (group: TaxonomicFilterGroup, value: TaxonomicFilterValue, item: any) => void = (
        taxonomicGroup,
        value,
        item
    ) => {
        selectItem(taxonomicGroup, value, item?.propertyFilterType)
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
    })
    const { filter, dropdownOpen, selectedCohortName, activeTaxonomicGroup } = useValues(logic)
    const { openDropdown, closeDropdown, selectItem } = useActions(logic)
    const valuePresent = filter?.type === 'cohort' || !!filter?.key
    const showInitialSearchInline =
        !disablePopover &&
        ((!filter?.type && (!filter || !(filter as any)?.key)) || filter?.type === PropertyFilterType.HogQL)
    const showOperatorValueSelect =
        filter?.type &&
        filter?.key &&
        !(filter?.type === PropertyFilterType.HogQL) &&
        !(filter?.type === PropertyFilterType.Cohort && restrictFeatureFlagCohortOperators)
    const placeOperatorValueSelectOnLeft = filter?.type && filter?.key && filter?.type === PropertyFilterType.Cohort

    const { propertyDefinitionsByType } = useValues(propertyDefinitionsModel)

    // We don't support array filter values here. Multiple-cohort only supported in TaxonomicBreakdownFilter.
    // This is mostly to make TypeScript happy.
    const cohortOrOtherValue =
        filter?.type === 'cohort' ? (!Array.isArray(filter?.value) && filter?.value) || undefined : filter?.key

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
            optionsFromProp={taxonomicFilterOptionsFromProp}
        />
    )

    const operatorValueSelect = (
        <OperatorValueSelect
            propertyDefinitions={propertyDefinitionsByType(
                filter?.type || PropertyDefinitionType.Event,
                isGroupPropertyFilter(filter) ? filter?.group_type_index : undefined
            )}
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
                        ...(isGroupPropertyFilter(filter) ? { group_type_index: filter.group_type_index } : {}),
                    } as AnyPropertyFilter)
                }
                if (newOperator && newValue && !isOperatorMulti(newOperator) && !isOperatorRegex(newOperator)) {
                    onComplete()
                }
            }}
            restrictFeatureFlagCohortOperators={restrictFeatureFlagCohortOperators}
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
                    })}
                >
                    {hasRowOperator && (
                        <div className="TaxonomicPropertyFilter__row-operator">
                            {orFiltering ? (
                                <>
                                    {propertyGroupType && index !== 0 && filter?.key && (
                                        <div className="text-sm font-medium">
                                            {propertyGroupType === FilterLogicalOperator.And ? '&' : propertyGroupType}
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
                            >
                                {filter?.type === 'cohort' ? (
                                    selectedCohortName || `Cohort #${filter?.value}`
                                ) : filter?.key ? (
                                    <PropertyKeyInfo
                                        value={filter.key}
                                        disablePopover
                                        ellipsis
                                        type={PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE[filter.type]}
                                    />
                                ) : (
                                    addText || 'Add filter'
                                )}
                            </LemonButton>
                        </LemonDropdown>
                        {showOperatorValueSelect && !placeOperatorValueSelectOnLeft && operatorValueSelect}
                    </div>
                </div>
            )}
        </div>
    )
}
