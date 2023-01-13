import { useValues } from 'kea'
import { QueryEditorFilterProps } from '~/types'
import { BreakdownFilter } from 'scenes/insights/filters/BreakdownFilter'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { isTrendsQuery } from '~/queries/utils'
import { queryNodeToFilter } from '../InsightQuery/utils/queryNodeToFilter'

export function Breakdown({ query }: QueryEditorFilterProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    const useMultiBreakdown = !isTrendsQuery(query) && !!featureFlags[FEATURE_FLAGS.BREAKDOWN_BY_MULTIPLE_PROPERTIES]

    const filters = queryNodeToFilter(query)
    const setFiltersMerge = (attrs: any): void => {
        console.log('BreakdownFilter.setFiltersMerge: ', attrs)
    }

    return <BreakdownFilter filters={filters} setFilters={setFiltersMerge} useMultiBreakdown={useMultiBreakdown} />
}
