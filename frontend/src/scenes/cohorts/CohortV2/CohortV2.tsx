import React from 'react'
import { useActions, useValues } from 'kea'
import { CohortNameInput } from './CohortNameInput'
import { CohortDescriptionInput } from './CohortDescriptionInput'
import { CohortTypeSelector } from './CohortTypeSelector'
import { Divider } from 'antd'
import { CohortMatchingCriteriaSection } from './CohortMatchingCriteriaSection'
import { CohortGroupType, CohortType } from '~/types'
import { cohortLogic } from '../cohortLogic'
import { PROPERTY_MATCH_TYPE } from 'lib/constants'

export function CohortV2(props: { cohort: CohortType }): JSX.Element {
    const logic = cohortLogic(props)
    const { setCohort } = useActions(logic)
    const { cohort } = useValues(logic)

    const onNameChange = (name: string): void => {
        setCohort({
            ...cohort,
            name,
        })
    }

    const onDescriptionChange = (description: string): void => {
        setCohort({
            ...cohort,
            description,
        })
    }

    const onCriteriaChange = (_group: Partial<CohortGroupType>, id: string): void => {
        const index = cohort.groups.findIndex((group: CohortGroupType) => group.id === id)
        cohort.groups[index] = {
            ...cohort.groups[index],
            ..._group,
        }
        setCohort({ ...cohort })
    }

    const onAddGroup = (): void => {
        cohort.groups = [
            ...cohort.groups,
            {
                id: Math.random().toString().substr(2, 5),
                matchType: PROPERTY_MATCH_TYPE,
            },
        ]
        setCohort({ ...cohort })
    }

    const onRemoveGroup = (index: number): void => {
        cohort.groups.splice(index, 1)
        setCohort({ ...cohort })
    }

    return (
        <div style={{ maxWidth: 1200 }} className="mb">
            <div style={{ display: 'flex', flexDirection: 'row' }}>
                <div style={{ flex: 6 }}>
                    <CohortNameInput input={cohort.name} onChange={onNameChange} />
                </div>
                <div style={{ flex: 4, marginLeft: 20 }}>
                    <CohortTypeSelector />
                </div>
            </div>
            <div style={{ display: 'flex', flexDirection: 'row' }}>
                <div style={{ flex: 6 }}>
                    <CohortDescriptionInput description={cohort.description} onChange={onDescriptionChange} />
                </div>
                <div style={{ flex: 4, marginLeft: 20 }} />
            </div>

            <Divider />
            <CohortMatchingCriteriaSection
                onCriteriaChange={onCriteriaChange}
                cohort={cohort}
                onAddGroup={onAddGroup}
                onRemoveGroup={onRemoveGroup}
            />
        </div>
    )
}
