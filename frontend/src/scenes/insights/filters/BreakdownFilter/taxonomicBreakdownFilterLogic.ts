import { actions, connect, kea, key, listeners, path, props, selectors } from 'kea'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { BreakdownFilter } from '~/queries/schema'
import { FilterType } from '~/types'
import { onAddBreakdown } from './taxonomicBreakdownFilterUtils'
import { propertyFilterTypeToTaxonomicFilterType } from 'lib/components/PropertyFilters/utils'
import { groupsModel } from '~/models/groupsModel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import type { taxonomicBreakdownFilterLogicType } from './taxonomicBreakdownFilterLogicType'

export interface TaxonomicBreakdownFilterLogicProps {
    breakdownFilter?: BreakdownFilter
    setFilters?: (filters: Partial<FilterType>, mergeFilters?: boolean) => void
    useMultiBreakdown: boolean
}

export const taxonomicBreakdownFilterLogic = kea<taxonomicBreakdownFilterLogicType>([
    props({} as TaxonomicBreakdownFilterLogicProps),
    path(['scenes', 'insights', 'filters', 'BreakdownFilter', 'taxonomicBreakdownFilterLogic']),
    connect({
        values: [
            // propertyDefinitionsModel, ['getPropertyDefinition'],
            groupsModel,
            ['groupsTaxonomicTypes'],
        ],
    }),
    actions({
        addBreakdown: (redirectToViewMode = true) => ({ redirectToViewMode }),
    }),
    selectors({
        hasSingleBreakdown: [
            (_, p) => [p.breakdownFilter],
            (breakdownFilter) => breakdownFilter?.breakdown && typeof breakdownFilter.breakdown === 'string',
        ],
        canEdit: [(_, p) => [p.setFilters], (setFilters) => !!setFilters],
        canAddBreakdown: [
            (s, p) => [s.canEdit, s.hasSingleBreakdown, p.useMultiBreakdown],
            (canEdit, hasSingleBreakdown, useMultiBreakdown) => canEdit && (!hasSingleBreakdown || useMultiBreakdown),
        ],
        supportsSessions: [
            () => [],
            () => {
                // TODO: implement based on insight type
                // includeSessions={filters.insight === InsightType.TRENDS}
                return false
            },
        ],
        breakdownArray: [
            (_, p) => [p.useMultiBreakdown, p.breakdownFilter],
            (useMultiBreakdown, breakdownFilter) =>
                useMultiBreakdown
                    ? (breakdownFilter?.breakdowns || []).map((b) => b.property)
                    : (Array.isArray(breakdownFilter?.breakdown)
                          ? breakdownFilter?.breakdown
                          : [breakdownFilter?.breakdown]
                      ).filter((b): b is string | number => !!b),
        ],
        breakdownParts: [
            (s) => [s.breakdownArray],
            (breakdownArray) => breakdownArray.map((b) => (isNaN(Number(b)) ? b : Number(b))),
        ],
        taxonomicGroupType: [
            (p) => [p.breakdownFilter],
            (breakdownFilter) => {
                let taxonomicBreakdownType = propertyFilterTypeToTaxonomicFilterType(breakdownFilter?.breakdown_type)
                if (taxonomicBreakdownType === TaxonomicFilterGroupType.Cohorts) {
                    taxonomicBreakdownType = TaxonomicFilterGroupType.CohortsWithAllUsers
                } else {
                }
            },
        ],
        taxonomicGroupTypes: [
            (s) => [s.groupsTaxonomicTypes, s.supportsSessions],
            (groupsTaxonomicTypes, supportsSessions) => [
                TaxonomicFilterGroupType.EventProperties,
                TaxonomicFilterGroupType.PersonProperties,
                TaxonomicFilterGroupType.EventFeatureFlags,
                ...groupsTaxonomicTypes,
                TaxonomicFilterGroupType.CohortsWithAllUsers,
                ...(supportsSessions ? [TaxonomicFilterGroupType.Sessions] : []),
                TaxonomicFilterGroupType.HogQLExpression,
            ],
        ],
    }),
    listeners(({ props, values }) => ({
        addBreakdown: () => {
            onAddBreakdown({
                useMultiBreakdown: props.useMultiBreakdown,
                breakdownParts: values.breakdownParts,
                setFilters: props.setFilters,
                getPropertyDefinition: values.getPropertyDefinition,
            })
        },
    })),
])
