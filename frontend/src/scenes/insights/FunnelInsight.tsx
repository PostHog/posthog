import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React from 'react'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { Funnel } from 'scenes/funnels/Funnel'
import { FunnelLayout } from 'lib/constants'
import { FunnelVizType, InsightType } from '~/types'
import { PersonsModal } from 'scenes/trends/PersonsModal'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

export function FunnelInsight(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { isValidFunnel, insightLoading, filters, areFiltersValid, barGraphLayout, aggregationTargetLabel } =
        useValues(funnelLogic(insightProps))
    const { showingPeople, cohortModalVisible } = useValues(personsModalLogic)
    const { setCohortModalVisible } = useActions(personsModalLogic)

    const nonEmptyState = (isValidFunnel && areFiltersValid) || insightLoading
    const noPadding = filters.funnel_viz_type == FunnelVizType.Steps && barGraphLayout === FunnelLayout.vertical

    return (
        <>
            <PersonsModal
                visible={showingPeople && !cohortModalVisible}
                view={InsightType.FUNNELS}
                filters={filters}
                onSaveCohort={() => {
                    setCohortModalVisible(true)
                }}
                showModalActions={filters.aggregation_group_type_index == undefined}
                aggregationTargetLabel={aggregationTargetLabel}
            />
            <div
                className={clsx('funnel-insights-container', {
                    'non-empty-state': nonEmptyState,
                    'no-padding': noPadding,
                })}
            >
                <Funnel />
            </div>
        </>
    )
}
