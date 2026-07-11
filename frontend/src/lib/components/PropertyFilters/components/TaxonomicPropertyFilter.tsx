import './TaxonomicPropertyFilter.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton, LemonDropdown, Link } from '@posthog/lemon-ui'

import { OperatorValueSelect } from 'lib/components/PropertyFilters/components/OperatorValueSelect'
import { PropertyFilterInternalProps } from 'lib/components/PropertyFilters/types'
import {
    PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE,
    isGroupPropertyFilter,
    isPropertyFilterWithOperator,
    propertyFilterTypeToTaxonomicFilterType,
    sanitizePropertyFilter,
} from 'lib/components/PropertyFilters/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { taxonomicTriggerWrapperClassName } from 'lib/components/TaxonomicFilter/menu/triggerLayout'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterValue,
    isKeyOnlyForGroup,
} from 'lib/components/TaxonomicFilter/types'
import { taxonomicMenuPreferenceLogic } from 'lib/components/TaxonomicPopover/taxonomicMenuPreferenceLogic'
import { TaxonomicMenuToggle } from 'lib/components/TaxonomicPopover/TaxonomicMenuToggle'
import { TaxonomicPopoverMenu } from 'lib/components/TaxonomicPopover/TaxonomicPopoverMenu'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { isOperatorMulti, isOperatorRegex } from 'lib/utils/operators'
import { toParams } from 'lib/utils/url'
import { teamLogic } from 'scenes/teamLogic'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import {
    AnyPropertyFilter,
    FilterLogicalOperator,
    GroupTypeIndex,
    PropertyDefinitionType,
    PropertyFilterType,
} from '~/types'

import { joinsLogic } from 'products/data_warehouse/frontend/shared/logics/joinsLogic'

import { OperandTag } from './OperandTag'
import { taxonomicPropertyFilterLogic } from './taxonomicPropertyFilterLogic'

export const DEFAULT_TAXONOMIC_GROUP_TYPES = [
    // Only materializes when the picker is scoped to $mcp_* events (see taxonomicGroups),
    // leading with the known MCP schema there; a no-op everywhere else.
    TaxonomicFilterGroupType.MCPProperties,
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
    dataWarehouseTableName,
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
    excludedOperators,
    selectingKeyOnly,
    hideBehavioralCohorts,
    addFilterDocLink,
    editable = true,
    operatorAllowlist,
    endpointFilters,
    hogQLGlobals,
    triggerVariant = 'button',
}: PropertyFilterInternalProps): JSX.Element {
    const generatedKey = useId()
    const pageKey = pageKeyInput || `filter-${generatedKey}`
    const baseGroupTypes = taxonomicGroupTypes || DEFAULT_TAXONOMIC_GROUP_TYPES
    const groupTypes = [TaxonomicFilterGroupType.SuggestedFilters, ...baseGroupTypes]
    const taxonomicOnChange: (group: TaxonomicFilterGroup, value: TaxonomicFilterValue, item: any) => void = (
        taxonomicGroup,
        value,
        item
    ) => {
        selectItem(taxonomicGroup, value, item?.propertyFilterType, item)
        if (
            taxonomicGroup.type === TaxonomicFilterGroupType.HogQLExpression ||
            taxonomicGroup.type === TaxonomicFilterGroupType.SuggestedFilters ||
            (taxonomicGroup.type === TaxonomicFilterGroupType.RecentFilters && item?._recentContext?.propertyFilter)
        ) {
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
        endpointFilters,
    })
    const { dropdownOpen, activeTaxonomicGroup } = useValues(logic)
    const filter = filters[index] ? sanitizePropertyFilter(filters[index]) : null
    const { openDropdown, closeDropdown, selectItem } = useActions(logic)
    const valuePresent = filter?.type === 'cohort' || !!filter?.key
    const showInitialSearchInline =
        !disablePopover &&
        ((!filter?.type && (!filter || !(filter as any)?.key)) || filter?.type === PropertyFilterType.HogQL)
    const filterTaxonomicGroupType = filter ? propertyFilterTypeToTaxonomicFilterType(filter) : undefined
    const isKeyOnlyRow = isKeyOnlyForGroup(selectingKeyOnly, filterTaxonomicGroupType)
    const showOperatorValueSelect =
        filter?.type && filter?.key && !(filter?.type === PropertyFilterType.HogQL) && !isKeyOnlyRow
    const placeOperatorValueSelectOnLeft = filter?.type && filter?.key && filter?.type === PropertyFilterType.Cohort

    const { propertyDefinitionsByType } = useValues(propertyDefinitionsModel)
    const { cohortsById } = useValues(cohortsModel)
    const { columnsJoinedToPersons } = useValues(joinsLogic)
    const { currentTeamId } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { useNewMenu } = useValues(taxonomicMenuPreferenceLogic)
    const menuRebuildEnabled = !!featureFlags[FEATURE_FLAGS.TAXONOMIC_FILTER_MENU_REBUILD]

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

    // Look up cohort name, if not already provided in filter
    const cohortValue =
        filter?.type === PropertyFilterType.Cohort && !Array.isArray(filter?.value) ? filter.value : undefined
    const cohortName =
        filter?.type === PropertyFilterType.Cohort
            ? filter.cohort_name ||
              (cohortValue !== undefined
                  ? cohortsById[cohortValue]?.name || cohortsById[String(cohortValue)]?.name
                  : undefined)
            : undefined

    const taxonomicFilter = (
        <TaxonomicFilter
            groupType={filterTaxonomicGroupType}
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
            selectFirstItem={!cohortOrOtherValue}
            endpointFilters={endpointFilters}
            hogQLGlobals={hogQLGlobals}
            excludedOperators={excludedOperators}
            selectingKeyOnly={selectingKeyOnly}
            enableKeywordShortcuts
            collapseUrlsToContainsRow
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
            endpoint={
                filter?.key &&
                filter?.type === PropertyFilterType.DataWarehouse &&
                dataWarehouseTableName &&
                currentTeamId
                    ? `api/environments/${currentTeamId}/data_warehouse/property_values?${toParams({
                          table_name: dataWarehouseTableName,
                          key: filter.key,
                      })}`
                    : filter?.key && activeTaxonomicGroup?.valuesEndpoint?.(filter.key)
            }
            eventNames={eventNames}
            addRelativeDateTimeOptions={allowRelativeDateOptions}
            onChange={(newOperator, newValue) => {
                if (filter?.key && filter?.type) {
                    setFilter(index, {
                        key: filter?.key,
                        value: newValue === undefined ? null : newValue,
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
            groupKeyNames={
                isGroupPropertyFilter(filter) && 'group_key_names' in filter
                    ? (filter as any).group_key_names
                    : undefined
            }
            operatorAllowlist={operatorAllowlist}
        />
    )

    const filterContent =
        filter?.type === 'cohort'
            ? cohortName || `Cohort #${filter?.value}`
            : filter?.type === PropertyFilterType.EventMetadata && filter?.key?.startsWith('$group_')
              ? filter.label || `Group ${filter?.value}`
              : filter?.type === PropertyFilterType.Flag && filter?.label
                ? filter.label
                : filter?.key && (
                      <PropertyKeyInfo
                          value={filter.key}
                          disablePopover
                          ellipsis
                          type={PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE[filter.type]}
                      />
                  )

    const legacyDropdown = (
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
                truncate={true}
                tooltip={
                    <>
                        {filterContent ?? (addText || 'Add filter')}
                        {addFilterDocLink && (
                            <>
                                <br />
                                <Link to={addFilterDocLink} target="_blank">
                                    Read the docs
                                </Link>
                            </>
                        )}
                    </>
                }
            >
                {filterContent ?? (addText || 'Add filter')}
            </LemonButton>
        </LemonDropdown>
    )

    // The rebuilt menu is a self-contained popover, so it only replaces the
    // row-branch dropdown variant. The truly inline mode is already routed
    // away via `showInitialSearchInline`; `disablePopover` still renders a
    // button + dropdown here, so it's fine to swap.
    //
    // Key-only rows route through the rebuilt menu too — the picker fires
    // the same `taxonomicOnChange` callback in either mode, so the commit
    // shape is identical (cohort id → `setFilter` with `type: 'cohort'`).
    //
    // The rebuilt menu carries its own toggle inside its trigger wrapper, so
    // it needs no extra DOM and inherits the row's layout exactly. The
    // legacy path gets a thin positioned wrapper to host the floating toggle.
    const editablePicker = !menuRebuildEnabled ? (
        legacyDropdown
    ) : useNewMenu ? (
        <TaxonomicPopoverMenu
            groupType={filterTaxonomicGroupType ?? groupTypes[0]}
            value={cohortOrOtherValue}
            groupTypes={groupTypes}
            onChange={(value, _groupType, item, group) => taxonomicOnChange(group, value, item)}
            renderValue={() => <span className="truncate">{filterContent}</span>}
            placeholder={addText || 'Add filter'}
            metadataSource={metadataSource}
            eventNames={eventNames}
            schemaColumns={schemaColumns}
            excludedProperties={excludedProperties}
            propertyAllowList={propertyAllowList}
            optionsFromProp={taxonomicFilterOptionsFromProp}
            hideBehavioralCohorts={hideBehavioralCohorts}
            endpointFilters={endpointFilters}
            hogQLGlobals={hogQLGlobals}
            enableKeywordShortcuts
            triggerVariant={triggerVariant}
            triggerButtonProps={{
                type: 'secondary',
                size,
                truncate: true,
                sideIcon: null,
                fullWidth: triggerVariant === 'input',
                icon: !valuePresent ? <IconPlusSmall /> : undefined,
            }}
        />
    ) : (
        <span className={taxonomicTriggerWrapperClassName()}>
            {legacyDropdown}
            <TaxonomicMenuToggle />
        </span>
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
                        {editable ? editablePicker : filterContent}
                        {showOperatorValueSelect && !placeOperatorValueSelectOnLeft && operatorValueSelect}
                    </div>
                </div>
            )}
        </div>
    )
}
