import { kea, path, props, selectors } from 'kea'
import { propertyFilterTypeToTaxonomicFilterType } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { BreakdownFilter } from '~/queries/schema'

import type { taxonomicBreakdownFilterLogicType } from './taxonomicBreakdownFilterLogicType'

type TaxonomicBreakdownFilterLogicProps = {
    filters: BreakdownFilter
}

export const taxonomicBreakdownFilterLogic = kea<taxonomicBreakdownFilterLogicType>([
    path(['scenes', 'insights', 'filters', 'BreakdownFilter', 'taxonomicBreakdownFilterLogic']),
    props({} as TaxonomicBreakdownFilterLogicProps),
    selectors({
        hasSelectedBreakdown: [(_, p) => [p.filters], ({ breakdown }) => breakdown && typeof breakdown === 'string'],
        taxonomicBreakdownType: [
            (_, p) => [p.filters],
            ({ breakdown_type }) => {
                let breakdownType = propertyFilterTypeToTaxonomicFilterType(breakdown_type)
                if (breakdownType === TaxonomicFilterGroupType.Cohorts) {
                    breakdownType = TaxonomicFilterGroupType.CohortsWithAllUsers
                }
                return breakdownType
            },
        ],
    }),
])
