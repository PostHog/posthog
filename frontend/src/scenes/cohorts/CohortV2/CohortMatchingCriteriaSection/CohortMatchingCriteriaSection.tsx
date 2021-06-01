import React from 'react'
import { Col } from 'antd'
import { MatchCriteriaSelector } from './MatchCriteriaSelector'
import '../cohort.scss'
import { CohortGroupType, CohortType } from '~/types'

export function CohortMatchingCriteriaSection({
    onCriteriaChange,
    cohort,
    onAddGroup,
    onRemoveGroup,
}: {
    onCriteriaChange: (group: Partial<CohortGroupType>, id: string) => void
    cohort: CohortType
    onAddGroup: () => void
    onRemoveGroup: (index: number) => void
}): JSX.Element {
    return (
        <Col>
            <span className="header">Matching Criteria</span>
            <br />
            <span>
                Users who match the following criteria will be part of the cohort. Autonomatically updated continuously
            </span>
            <div style={{ marginTop: 20, marginBottom: 20 }}>
                {cohort.groups.map((group: CohortGroupType, index: number) => (
                    <React.Fragment key={index}>
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: '100%' }}>
                            <MatchCriteriaSelector
                                onCriteriaChange={(newGroup) => onCriteriaChange(newGroup, group.id)}
                                onRemove={() => onRemoveGroup(index)}
                                group={group}
                            />
                            {index < cohort.groups.length - 1 && (
                                <div className="stateful-badge mc-main or" style={{ marginTop: 15, marginBottom: 15 }}>
                                    OR
                                </div>
                            )}
                        </div>
                    </React.Fragment>
                ))}
            </div>
            <span onClick={() => onAddGroup()}>+ Add Matching Criteria</span>
        </Col>
    )
}
