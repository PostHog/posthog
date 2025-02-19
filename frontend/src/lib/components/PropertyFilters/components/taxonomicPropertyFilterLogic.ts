import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { TaxonomicPropertyFilterLogicProps } from 'lib/components/PropertyFilters/types'
import {
    createDefaultPropertyFilter,
    isAnyPropertyfilter,
    propertyFilterTypeToTaxonomicFilterType,
    sanitizePropertyFilter,
    taxonomicFilterTypeToPropertyFilterType,
} from 'lib/components/PropertyFilters/utils'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import {
    TaxonomicFilterGroup,
    TaxonomicFilterLogicProps,
    TaxonomicFilterValue,
} from 'lib/components/TaxonomicFilter/types'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { AnyPropertyFilter, CohortPropertyFilter, PropertyFilterType } from '~/types'

import type { taxonomicPropertyFilterLogicType } from './taxonomicPropertyFilterLogicType'

export const taxonomicPropertyFilterLogic = kea<taxonomicPropertyFilterLogicType>([
    props({} as TaxonomicPropertyFilterLogicProps),
    key((props) => `${props.pageKey}-${props.filterIndex}`),
    path((key) => ['lib', 'components', 'PropertyFilters', 'components', 'taxonomicPropertyFilterLogic', key]),
    connect((props: TaxonomicPropertyFilterLogicProps) => ({
        values: [
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
        selectItem: (
            taxonomicGroup: TaxonomicFilterGroup,
            propertyKey?: TaxonomicFilterValue,
            itemPropertyFilterType?: PropertyFilterType,
            item?: any
        ) => ({
            taxonomicGroup,
            propertyKey,
            itemPropertyFilterType,
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
            (_, p) => [p.filters, p.filterIndex],
            (filters, filterIndex): AnyPropertyFilter | null =>
                filters[filterIndex] ? sanitizePropertyFilter(filters[filterIndex]) : null,
        ],
        activeTaxonomicGroup: [
            (s) => [s.filter, s.taxonomicGroups],
            (filter, groups): TaxonomicFilterGroup | undefined => {
                if (isAnyPropertyfilter(filter)) {
                    const taxonomicGroupType = propertyFilterTypeToTaxonomicFilterType(filter)
                    return groups.find((group) => group.type === taxonomicGroupType)
                }
            },
        ],
    }),
    listeners(({ actions, values, props }) => ({
        selectItem: ({ taxonomicGroup, propertyKey, itemPropertyFilterType, item }) => {
            const propertyType = itemPropertyFilterType ?? taxonomicFilterTypeToPropertyFilterType(taxonomicGroup.type)
            if (propertyKey && propertyType) {
                const filter = createDefaultPropertyFilter(
                    values.filter,
                    propertyKey,
                    propertyType,
                    taxonomicGroup,
                    values.describeProperty
                )

                // Add cohort name if this is a cohort filter
                if (propertyType === 'cohort' && item?.name) {
                    const cohortFilter = filter as CohortPropertyFilter
                    cohortFilter.cohort_name = item.name
                }

                props.setFilter(props.filterIndex, filter)
                actions.closeDropdown()
            }
        },
    })),
])
