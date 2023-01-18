import { useValues, useActions } from 'kea'
import { QueryEditorFilterProps } from '~/types'
import { BreakdownFilter } from 'scenes/insights/filters/BreakdownFilter'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { isTrendsQuery } from '~/queries/utils'
import { queryNodeToFilter } from '../InsightQuery/utils/queryNodeToFilter'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { BreakdownFilter as BreakdownFilterType } from '~/queries/schema'

export function Breakdown({ insightProps, query }: QueryEditorFilterProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { updateBreakdown } = useActions(insightDataLogic(insightProps))

    const useMultiBreakdown = !isTrendsQuery(query) && !!featureFlags[FEATURE_FLAGS.BREAKDOWN_BY_MULTIPLE_PROPERTIES]

    // treat breakdown filter as black box for data exploration for now
    const filters = queryNodeToFilter(query)
    const setFilters = (breakdown: BreakdownFilterType): void => {
        updateBreakdown(breakdown)
    }
    return <BreakdownFilter filters={filters} setFilters={setFilters} useMultiBreakdown={useMultiBreakdown} />
}
