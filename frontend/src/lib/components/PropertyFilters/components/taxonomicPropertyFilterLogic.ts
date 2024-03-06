import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { TaxonomicPropertyFilterLogicProps } from 'lib/components/PropertyFilters/types'
import {
    isGroupPropertyFilter,
    isPropertyFilterWithOperator,
    propertyFilterTypeToPropertyDefinitionType,
    propertyFilterTypeToTaxonomicFilterType,
    sanitizePropertyFilter,
    taxonomicFilterTypeToPropertyFilterType,
} from 'lib/components/PropertyFilters/utils'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'

import { cohortsModel } from '~/models/cohortsModel'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import {
    AnyPropertyFilter,
    CohortPropertyFilter,
    HogQLPropertyFilter,
    PropertyDefinitionType,
    PropertyFilterType,
    PropertyOperator,
    PropertyType,
} from '~/types'

import type { taxonomicPropertyFilterLogicType } from './taxonomicPropertyFilterLogicType'

export const taxonomicPropertyFilterLogic = kea<taxonomicPropertyFilterLogicType>([
    props({} as TaxonomicPropertyFilterLogicProps),
    key((props) => `${props.pageKey}-${props.filterIndex}`),
    path((key) => ['lib', 'components', 'PropertyFilters', 'components', 'taxonomicPropertyFilterLogic', key]),
    connect((props: TaxonomicPropertyFilterLogicProps) => ({
        values: [
            props.propertyFilterLogic,
            ['filters'],
            taxonomicFilterLogic({
                taxonomicFilterLogicKey: props.pageKey,
                taxonomicGroupTypes: props.taxonomicGroupTypes,
                onChange: props.taxonomicOnChange,
                eventNames: props.eventNames,
                propertyAllowList: props.propertyAllowList,
            } as TaxonomicFilterLogicProps),
            ['taxonomicGroups'],
            propertyDefinitionsModel,
            ['describeProperty'],
        ],
    })),
    actions({
        selectItem: (taxonomicGroup: TaxonomicFilterGroup, propertyKey?: TaxonomicFilterValue, item?: any) => ({
            taxonomicGroup,
            propertyKey,
            item,
        }),
        openDropdown: true,
        closeDropdown: true,
    }),
    reducers({
        dropdownOpen: [
            false,
            {
                openDropdown: () => true,
                closeDropdown: () => false,
            },
        ],
    }),
    selectors({
        filter: [
            (s, p) => [s.filters, p.filterIndex],
            (filters, filterIndex): AnyPropertyFilter | null =>
                filters[filterIndex] ? sanitizePropertyFilter(filters[filterIndex]) : null,
        ],
        selectedCohortName: [
            (s) => [s.filter, cohortsModel.selectors.cohorts],
            (filter, cohorts) => (filter?.type === 'cohort' ? cohorts.find((c) => c.id === filter?.value)?.name : null),
        ],
        activeTaxonomicGroup: [
            (s) => [s.filter, s.taxonomicGroups],
            (filter, groups): TaxonomicFilterGroup | undefined => {
                if (isGroupPropertyFilter(filter)) {
                    const taxonomicGroupType = propertyFilterTypeToTaxonomicFilterType(filter)
                    return groups.find((group) => group.type === taxonomicGroupType)
                }
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        selectItem: ({ taxonomicGroup, propertyKey, item }) => {
            const itemPropertyFilterType = item?.propertyFilterType as PropertyFilterType
            const propertyType = itemPropertyFilterType ?? taxonomicFilterTypeToPropertyFilterType(taxonomicGroup.type)
            if (propertyKey && propertyType) {
                if (propertyType === PropertyFilterType.Cohort) {
                    const cohortProperty: CohortPropertyFilter = {
                        key: 'id',
                        value: parseInt(String(propertyKey)),
                        type: propertyType,
                    }
                    props.propertyFilterLogic.actions.setFilter(props.filterIndex, cohortProperty)
                } else if (propertyType === PropertyFilterType.HogQL) {
                    const hogQLProperty: HogQLPropertyFilter = {
                        type: propertyType,
                        key: String(propertyKey),
                        value: null, // must specify something to be compatible with existing types
                    }
                    props.propertyFilterLogic.actions.setFilter(props.filterIndex, hogQLProperty)
                } else {
                    const apiType =
                        propertyFilterTypeToPropertyDefinitionType(propertyType) ?? PropertyDefinitionType.Event

                    const propertyValueType = values.describeProperty(
                        propertyKey,
                        apiType,
                        taxonomicGroup.groupTypeIndex
                    )
                    const property_name_to_default_operator_override = {
                        $active_feature_flags: PropertyOperator.IContains,
                    }
                    const property_value_type_to_default_operator_override = {
                        [PropertyType.Duration]: PropertyOperator.GreaterThan,
                        [PropertyType.DateTime]: PropertyOperator.IsDateExact,
                        [PropertyType.Selector]: PropertyOperator.Exact,
                    }
                    const operator =
                        property_name_to_default_operator_override[propertyKey] ||
                        (isPropertyFilterWithOperator(values.filter) ? values.filter.operator : null) ||
                        property_value_type_to_default_operator_override[propertyValueType ?? ''] ||
                        PropertyOperator.Exact

                    const isGroupNameFilter = taxonomicGroup.type.startsWith(TaxonomicFilterGroupType.GroupNamesPrefix)
                    // :TRICKY: When we have a GroupNamesPrefix taxonomic filter, selecting the group name
                    // is the equivalent of selecting a property value
                    const property: AnyPropertyFilter = {
                        key: isGroupNameFilter ? '$group_key' : propertyKey.toString(),
                        value: isGroupNameFilter ? propertyKey.toString() : null,
                        operator,
                        type: propertyType as AnyPropertyFilter['type'] as any, // bad | pipe chain :(
                        group_type_index: taxonomicGroup.groupTypeIndex,
                        table_name: item.table,
                    }
                    props.propertyFilterLogic.actions.setFilter(props.filterIndex, property)
                }
                actions.closeDropdown()
            }
        },
    })),
])
