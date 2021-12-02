import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React from 'react'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { Funnel } from 'scenes/funnels/Funnel'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS, FunnelLayout } from 'lib/constants'
import { FunnelVizType, InsightType } from '~/types'
import { PersonsModal } from 'scenes/trends/PersonsModal'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

export function FunnelInsight(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { isValidFunnel, isLoading, filters, areFiltersValid, barGraphLayout } = useValues(funnelLogic(insightProps))
    const { featureFlags } = useValues(featureFlagLogic)
    const { showingPeople, cohortModalVisible } = useValues(personsModalLogic)
    const { setCohortModalVisible } = useActions(personsModalLogic)

    return (
        <>
            <PersonsModal
                visible={showingPeople && !cohortModalVisible}
                view={InsightType.FUNNELS}
                filters={filters}
                onSaveCohort={() => {
                    setCohortModalVisible(true)
                }}
                showModalActions={filters.aggregation_group_type_index != undefined}
            />
            <div
                className={clsx('funnel-insights-container', {
                    'non-empty-state': (isValidFunnel && areFiltersValid) || isLoading,
                    'no-padding':
                        featureFlags[FEATURE_FLAGS.FUNNEL_VERTICAL_BREAKDOWN] &&
                        filters.funnel_viz_type == FunnelVizType.Steps &&
                        barGraphLayout === FunnelLayout.vertical,
                })}
            >
                <Funnel />
            </div>
        </>
    )
}
