import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import React from 'react'
import { funnelLogic } from 'scenes/funnels/funnelLogic'
import { Funnel } from 'scenes/funnels/Funnel'
import { InsightType } from '~/types'
import { PersonsModal } from 'scenes/trends/persons-modal/PersonsModal'
import { personsModalLogic } from 'scenes/trends/persons-modal/personsModalLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { SaveCohortModal } from 'scenes/trends/persons-modal/SaveCohortModal'

export function FunnelInsight(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { isValidFunnel, insightLoading, filters, areFiltersValid, aggregationTargetLabel } = useValues(
        funnelLogic(insightProps)
    )
    const { showingPeople, cohortModalVisible } = useValues(personsModalLogic)
    const { setCohortModalVisible, saveCohortWithUrl } = useActions(personsModalLogic)

    const nonEmptyState = (isValidFunnel && areFiltersValid) || insightLoading

    return (
        <>
            <PersonsModal
                isOpen={showingPeople && !cohortModalVisible}
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
                })}
            >
                <Funnel />
            </div>
            <SaveCohortModal
                isOpen={cohortModalVisible}
                onSave={(title: string) => {
                    saveCohortWithUrl(title)
                    setCohortModalVisible(false)
                }}
                onCancel={() => setCohortModalVisible(false)}
            />
        </>
    )
}
