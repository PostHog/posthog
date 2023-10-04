import './TaxonomicPropertyFilter.scss'
import { useMemo } from 'react'
import { useActions, useMountedLogic, useValues } from 'kea'
import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'
import { taxonomicPropertyFilterLogic } from './taxonomicPropertyFilterLogic'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { OperatorValueSelect } from 'lib/components/PropertyFilters/components/OperatorValueSelect'
import { isOperatorMulti, isOperatorRegex } from 'lib/utils'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'
import {
    isGroupPropertyFilter,
    isPropertyFilterWithOperator,
    propertyFilterTypeToTaxonomicFilterType,
} from 'lib/components/PropertyFilters/utils'
import { PropertyFilterInternalProps } from 'lib/components/PropertyFilters/types'
import clsx from 'clsx'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { AnyPropertyFilter, FilterLogicalOperator, PropertyDefinitionType, PropertyFilterType } from '~/types'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LemonButtonWithDropdown } from '@posthog/lemon-ui'
import { IconPlusMini } from 'lib/lemon-ui/icons'

let uniqueMemoizedIndex = 0

export function TaxonomicPropertyFilter({
    pageKey: pageKeyInput,
    index,
    onComplete,
    disablePopover, // inside a dropdown if this is false
    taxonomicGroupTypes,
    eventNames,
    propertyGroupType,
    orFiltering,
    addText = 'Add filter',
    hasRowOperator,
    hogQLTable,
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
        value
    ) => {
        selectItem(taxonomicGroup, value)
        if (
            taxonomicGroup.type === TaxonomicFilterGroupType.Cohorts ||
            taxonomicGroup.type === TaxonomicFilterGroupType.HogQLExpression
        ) {
            onComplete?.()
        }
    }
    const builtPropertyFilterLogic = useMountedLogic(propertyFilterLogic)
    const { setFilter } = useActions(propertyFilterLogic)

    const logic = taxonomicPropertyFilterLogic({
        pageKey,
        propertyFilterLogic: builtPropertyFilterLogic,
        filterIndex: index,
        taxonomicGroupTypes: groupTypes,
        taxonomicOnChange,
        eventNames,
    })
    const { filter, dropdownOpen, selectedCohortName, activeTaxonomicGroup } = useValues(logic)
    const { openDropdown, closeDropdown, selectItem } = useActions(logic)
    const valuePresent = filter?.type === 'cohort' || !!filter?.key
    const showInitialSearchInline =
        !disablePopover &&
        ((!filter?.type && (!filter || !(filter as any)?.key)) ||
            filter?.type === PropertyFilterType.Cohort ||
            filter?.type === PropertyFilterType.HogQL)
    const showOperatorValueSelect =
        filter?.type &&
        filter?.key &&
        filter?.type !== PropertyFilterType.Cohort &&
        filter?.type !== PropertyFilterType.HogQL

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
            hogQLTable={hogQLTable}
            eventNames={eventNames}
        />
    )

    const { ref: wrapperRef, size } = useResizeBreakpoints({
        0: 'tiny',
        400: 'small',
        550: 'medium',
    })

    return (
        <div
            className={clsx('TaxonomicPropertyFilter', {
                'TaxonomicPropertyFilter--in-dropdown': !showInitialSearchInline && !disablePopover,
            })}
            ref={wrapperRef}
        >
            {showInitialSearchInline ? (
                taxonomicFilter
            ) : (
                <div
                    className={clsx('TaxonomicPropertyFilter__row', {
                        [`width-${size}`]: true,
                        'TaxonomicPropertyFilter__row--or-filtering': orFiltering,
                        'TaxonomicPropertyFilter__row--showing-operators': showOperatorValueSelect,
                    })}
                >
                    {hasRowOperator && (
                        <div className="TaxonomicPropertyFilter__row__operator">
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
                                            <span className="arrow">&#8627;</span>
                                            <span>where</span>
                                        </>
                                    ) : (
                                        <span className="stateful-badge and text-xs">AND</span>
                                    )}
                                </div>
                            )}
                        </div>
                    )}
                    <div className="TaxonomicPropertyFilter__row__items">
                        <LemonButtonWithDropdown
                            dropdown={{
                                overlay: dropdownOpen ? taxonomicFilter : null,
                                visible: dropdownOpen,
                                placement: 'bottom',
                                onClickOutside: closeDropdown,
                            }}
                            onClick={() => (dropdownOpen ? closeDropdown() : openDropdown())}
                            type="secondary"
                            status={!valuePresent ? 'primary' : 'stealth'}
                            icon={!valuePresent ? <IconPlusMini /> : undefined}
                            sideIcon={null}
                            data-attr={'property-select-toggle-' + index}
                        >
                            {filter?.type === 'cohort' ? (
                                selectedCohortName || `Cohort #${filter?.value}`
                            ) : filter?.key ? (
                                <PropertyKeyInfo value={filter.key} disablePopover ellipsis />
                            ) : (
                                addText || 'Add filter'
                            )}
                        </LemonButtonWithDropdown>
                        {showOperatorValueSelect ? (
                            <OperatorValueSelect
                                propertyDefinitions={propertyDefinitionsByType(
                                    filter?.type || PropertyDefinitionType.Event
                                )}
                                type={filter?.type}
                                propkey={filter?.key}
                                operator={isPropertyFilterWithOperator(filter) ? filter.operator : null}
                                value={filter?.value}
                                placeholder="Enter value..."
                                endpoint={filter?.key && activeTaxonomicGroup?.valuesEndpoint?.(filter.key)}
                                eventNames={eventNames}
                                onChange={(newOperator, newValue) => {
                                    if (filter?.key && filter?.type) {
                                        setFilter(index, {
                                            key: filter?.key,
                                            value: newValue || null,
                                            operator: newOperator,
                                            type: filter?.type,
                                            ...(isGroupPropertyFilter(filter)
                                                ? { group_type_index: filter.group_type_index }
                                                : {}),
                                        } as AnyPropertyFilter)
                                    }
                                    if (
                                        newOperator &&
                                        newValue &&
                                        !isOperatorMulti(newOperator) &&
                                        !isOperatorRegex(newOperator)
                                    ) {
                                        onComplete()
                                    }
                                }}
                            />
                        ) : (
                            <div />
                        )}
                    </div>
                </div>
            )}
        </div>
    )
}
