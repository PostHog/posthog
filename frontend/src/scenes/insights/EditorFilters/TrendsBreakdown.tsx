import React from 'react'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { EditorFilterProps, InsightType } from '~/types'
import { BreakdownFilter } from 'scenes/insights/filters/BreakdownFilter'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export function TrendsBreakdown({ filters, insightProps }: EditorFilterProps): JSX.Element {
    const { setFilters } = useActions(trendsLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)

    const useMultiBreakdown =
        filters.insight !== InsightType.TRENDS && !!featureFlags[FEATURE_FLAGS.BREAKDOWN_BY_MULTIPLE_PROPERTIES]

    return <BreakdownFilter filters={filters} setFilters={setFilters} useMultiBreakdown={useMultiBreakdown} />
}
