import React from 'react'
import { Col } from 'antd'
import { MatchCriteriaSelector } from './MatchCriteriaSelector'

export function CohortMatchingCriteriaSection(): JSX.Element {
    return (
        <Col>
            <span>Matching Criteria</span>
            <span>
                Users who match the following criteria will be part of the cohort. Autonomatically updated continuously
            </span>
            <MatchCriteriaSelector onChange={() => {}} />
        </Col>
    )
}
