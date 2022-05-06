import React from 'react'
import { useActions, useValues } from 'kea'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { EditorFilterProps } from '~/types'
import { BreakdownFilter } from 'scenes/insights/BreakdownFilter'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export function EFTrendsBreakdown({ filters, insightProps }: EditorFilterProps): JSX.Element {
    const { setFilters } = useActions(trendsLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <BreakdownFilter
            filters={filters}
            setFilters={setFilters}
            buttonType="default"
            useMultiBreakdown={!!featureFlags[FEATURE_FLAGS.BREAKDOWN_BY_MULTIPLE_PROPERTIES]}
        />
    )
}
