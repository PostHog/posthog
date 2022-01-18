import React from 'react'
import { Row, Col } from 'antd'
import { CohortType } from '~/types'
import { TeamMemberID } from 'lib/components/TeamMemberID'
import { dayjs } from 'lib/dayjs'

export function CohortDetailsRow({ cohort }: { cohort: CohortType }): JSX.Element {
    const columnSize = 12
    return (
        <Row justify="space-between" align="top" className="mt text-center">
            <Col span={columnSize}>
                <label className="ant-form-item-label">Created at</label>
                <div>{dayjs(cohort.created_at).fromNow()}</div>
            </Col>
            <Col span={columnSize}>
                <label className="ant-form-item-label">Created by</label>
                <div>
                    <TeamMemberID person={cohort.created_by} />
                </div>
            </Col>
            <Col span={columnSize}>
                <label className="ant-form-item-label">Last calculated at</label>

                <div>{cohort.last_calculation ? dayjs(cohort.last_calculation).fromNow() : 'in progress'}</div>
            </Col>
        </Row>
    )
}
