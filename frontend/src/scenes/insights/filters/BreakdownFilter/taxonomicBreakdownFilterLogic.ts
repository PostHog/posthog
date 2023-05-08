import { kea, path, props, selectors } from 'kea'
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
    }),
])
