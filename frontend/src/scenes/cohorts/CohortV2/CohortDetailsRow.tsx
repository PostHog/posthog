import React from 'react'
import { Row, Col } from 'antd'
import { CohortType } from '~/types'
import dayjs from 'dayjs'
import './cohort.scss'

export function CohortDetailsRow({ cohort }: { cohort: CohortType }): JSX.Element {
    return (
        <Row justify="space-between" align="top">
            <Col span={6}>
                <span className="sub-header">Created</span>
                <br />
                <span>{dayjs(cohort.created_at).fromNow()}</span>
            </Col>
            <Col span={6}>
                <span className="sub-header">Created By</span>
                <br />
                <span>{cohort.created_by?.first_name || cohort.created_by?.email}</span>
            </Col>
            <Col span={6}>
                <span className="sub-header">Last Calculated</span>
                <br />
                <span>{dayjs(cohort.last_calculation).fromNow()}</span>
            </Col>
            <Col span={6}>
                <span className="sub-header">Last Modified</span>
            </Col>
        </Row>
    )
}
