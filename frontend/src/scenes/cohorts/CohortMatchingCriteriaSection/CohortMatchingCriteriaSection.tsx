import React from 'react'
import { Col } from 'antd'
import { MatchCriteriaSelector } from './MatchCriteriaSelector'
import { CohortGroupType } from '~/types'
import { PlusOutlined } from '@ant-design/icons'
import { BuiltLogic, useActions, useValues } from 'kea'
import { cohortLogicType } from '../cohortLogicType'
import { PROPERTY_MATCH_TYPE } from 'lib/constants'

export function CohortMatchingCriteriaSection({ logic }: { logic: BuiltLogic<cohortLogicType> }): JSX.Element {
    const { setCohort, onCriteriaChange } = useActions(logic)
    const { cohort, submitted } = useValues(logic)
    const onAddGroup = (): void => {
        cohort.groups = [
            ...cohort.groups,
            {
                id: Math.random().toString().substr(2, 5),
                matchType: PROPERTY_MATCH_TYPE,
                properties: [],
            },
        ]
        setCohort({ ...cohort })
    }

    const onRemoveGroup = (index: number): void => {
        cohort.groups.splice(index, 1)
        setCohort({ ...cohort })
    }
    const addButton = (
        <div style={{ marginTop: 8, marginBottom: 8 }}>
            <a href="#add" style={{ padding: 0 }} onClick={() => onAddGroup()} data-attr="add-match-criteria">
                <PlusOutlined /> Add matching criteria
            </a>
        </div>
    )

    return (
        <Col>
            <h3 className="l3">Matching Criteria</h3>
            <div className="mb">
                Users who match the following criteria will be part of the cohort. Continuously updated automatically.
            </div>
            <div>
                {cohort.groups.map((group: CohortGroupType, index: number) => (
                    <React.Fragment key={index}>
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: '100%' }}>
                            <MatchCriteriaSelector
                                onCriteriaChange={(newGroup) => onCriteriaChange(newGroup, group.id)}
                                onRemove={() => onRemoveGroup(index)}
                                group={group}
                                showErrors={submitted}
                            />
                            {index < cohort.groups.length - 1 && <div className="stateful-badge or mt mb">OR</div>}
                        </div>
                    </React.Fragment>
                ))}
            </div>
            <span id="add" />
            {addButton}
        </Col>
    )
}
