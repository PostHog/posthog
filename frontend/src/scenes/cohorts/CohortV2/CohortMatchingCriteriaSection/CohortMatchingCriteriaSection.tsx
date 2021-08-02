import React from 'react'
import { Col } from 'antd'
import { MatchCriteriaSelector } from './MatchCriteriaSelector'
import { CohortGroupType, CohortType } from '~/types'
import { PlusOutlined } from '@ant-design/icons'

export function CohortMatchingCriteriaSection({
    onCriteriaChange,
    cohort,
    onAddGroup,
    onRemoveGroup,
    showErrors,
}: {
    onCriteriaChange: (group: Partial<CohortGroupType>, id: string) => void
    cohort: CohortType
    onAddGroup: () => void
    onRemoveGroup: (index: number) => void
    showErrors?: boolean
}): JSX.Element {
    const addButton = (
        <div style={{ marginTop: 8, marginBottom: 8 }}>
            <a href="#add" style={{ padding: 0 }} onClick={() => onAddGroup()}>
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
            {addButton}
            <div>
                {cohort.groups.map((group: CohortGroupType, index: number) => (
                    <React.Fragment key={index}>
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: '100%' }}>
                            <MatchCriteriaSelector
                                onCriteriaChange={(newGroup) => onCriteriaChange(newGroup, group.id)}
                                onRemove={() => onRemoveGroup(index)}
                                group={group}
                                showErrors={showErrors}
                            />
                            {index < cohort.groups.length - 1 && <div className="stateful-badge or mt mb">OR</div>}
                        </div>
                    </React.Fragment>
                ))}
            </div>
            <span id="add" />
            {!!cohort.groups.length && addButton}
        </Col>
    )
}
