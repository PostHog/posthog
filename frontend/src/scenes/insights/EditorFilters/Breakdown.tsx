import { useActions, useValues } from 'kea'
import { EditorFilterProps, InsightType } from '~/types'
import { TaxonomicBreakdownFilter } from 'scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownFilter'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { insightLogic } from 'scenes/insights/insightLogic'

export function Breakdown({ filters }: EditorFilterProps): JSX.Element {
    const { setFiltersMerge } = useActions(insightLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const useMultiBreakdown =
        filters.insight !== InsightType.TRENDS && !!featureFlags[FEATURE_FLAGS.BREAKDOWN_BY_MULTIPLE_PROPERTIES]

    return (
        <TaxonomicBreakdownFilter
            filters={filters}
            setFilters={setFiltersMerge}
            useMultiBreakdown={useMultiBreakdown}
        />
    )
}
