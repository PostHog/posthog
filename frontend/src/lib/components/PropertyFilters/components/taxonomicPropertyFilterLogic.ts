import { kea } from 'kea'
import { TaxonomicPropertyFilterLogicProps } from 'lib/components/PropertyFilters/types'
import { AnyPropertyFilter, PropertyFilterValue, PropertyOperator } from '~/types'
import type { taxonomicPropertyFilterLogicType } from './taxonomicPropertyFilterLogicType'
import { cohortsModel } from '~/models/cohortsModel'
import { TaxonomicFilterGroup } from 'lib/components/TaxonomicFilter/types'
import {
    propertyFilterTypeToTaxonomicFilterType,
    taxonomicFilterTypeToPropertyFilterType,
} from 'lib/components/PropertyFilters/utils'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'

export const taxonomicPropertyFilterLogic = kea<taxonomicPropertyFilterLogicType>({
    path: (key) => ['lib', 'components', 'PropertyFilters', 'components', 'taxonomicPropertyFilterLogic', key],
    props: {} as TaxonomicPropertyFilterLogicProps,
    key: (props) => `${props.pageKey}-${props.filterIndex}`,

    connect: (props: TaxonomicPropertyFilterLogicProps) => ({
        values: [
            props.propertyFilterLogic,
            ['filters'],
            taxonomicFilterLogic({
                taxonomicFilterLogicKey: props.pageKey,
                taxonomicGroupTypes: props.taxonomicGroupTypes,
                onChange: props.taxonomicOnChange,
                eventNames: props.eventNames,
            }),
            ['taxonomicGroups'],
        ],
    }),

    actions: {
        selectItem: (taxonomicGroup: TaxonomicFilterGroup, propertyKey?: PropertyFilterValue) => ({
            taxonomicGroup,
            propertyKey,
        }),
        openDropdown: true,
        closeDropdown: true,
    },

    reducers: {
        dropdownOpen: [
            false,
            {
                openDropdown: () => true,
                closeDropdown: () => false,
            },
        ],
    },

    selectors: {
        filter: [
            (s) => [s.filters, (_, props) => props.filterIndex],
            (filters, filterIndex): AnyPropertyFilter | null => filters[filterIndex] || null,
        ],
        selectedCohortName: [
            (s) => [s.filter, cohortsModel.selectors.cohorts],
            (filter, cohorts) => (filter?.type === 'cohort' ? cohorts.find((c) => c.id === filter?.value)?.name : null),
        ],
        activeTaxonomicGroup: [
            (s) => [s.filter, s.taxonomicGroups],
            (filter, groups): TaxonomicFilterGroup | undefined => {
                if (filter) {
                    const taxonomicGroupType = propertyFilterTypeToTaxonomicFilterType(
                        filter.type,
                        filter.group_type_index
                    )
                    return groups.find((group) => group.type === taxonomicGroupType)
                }
            },
        ],
    },

    listeners: ({ actions, values, props }) => ({
        selectItem: ({ taxonomicGroup, propertyKey }) => {
            const propertyType = taxonomicFilterTypeToPropertyFilterType(taxonomicGroup.type)
            if (propertyKey && propertyType) {
                if (propertyType === 'cohort') {
                    props.propertyFilterLogic.actions.setFilter(
                        props.filterIndex,
                        'id',
                        propertyKey,
                        null,
                        propertyType
                    )
                } else {
                    const operator =
                        propertyKey === '$active_feature_flags'
                            ? PropertyOperator.IContains
                            : values.filter?.operator || PropertyOperator.Exact

                    props.propertyFilterLogic.actions.setFilter(
                        props.filterIndex,
                        propertyKey.toString(),
                        null, // Reset value field
                        operator,
                        propertyType,
                        taxonomicGroup.groupTypeIndex
                    )
                }
                actions.closeDropdown()
            }
        },
    }),
})
