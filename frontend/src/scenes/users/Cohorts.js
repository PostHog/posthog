import React, { Component } from 'react'
import { Link } from 'lib/components/Link'
import moment from 'moment'
import { DeleteWithUndo } from 'lib/utils'
import { Tooltip, Table, Spin } from 'antd'
import { ExportOutlined, DeleteOutlined } from '@ant-design/icons'
import { cohortsModel } from '../../models/cohortsModel'
import { useValues, useActions } from 'kea'

export function Cohorts() {
    const { cohorts, cohortsLoading } = useValues(cohortsModel)
    const { loadCohorts } = useActions(cohortsModel)
    let columns = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            render: (_, cohort) => <Link to={'/people?cohort=' + cohort.id}>{cohort.name}</Link>,
        },
        {
            title: 'Last calculation',
            render: (_, cohort) =>
                cohort.is_calculating ? (
                    <span>
                        Calculating <Spin />
                    </span>
                ) : (
                    moment(cohort.last_calculation).fromNow()
                ),
        },
        {
            title: 'Actions',
            render: cohort => (
                <span>
                    <a href={'/api/person.csv?cohort=' + cohort.id}>
                        <Tooltip title="Export all users in this cohort as a .csv file">
                            <ExportOutlined />
                        </Tooltip>
                    </a>
                    <DeleteWithUndo
                        endpoint="cohort"
                        object={cohort}
                        className="text-danger"
                        style={{ marginLeft: 8 }}
                        callback={loadCohorts}
                    >
                        <DeleteOutlined />
                    </DeleteWithUndo>
                </span>
            ),
        },
    ]

    return (
        <div>
            <h1>Cohorts</h1>
            <Link to={'/people?new_cohort='} className="btn btn-outline-success btn-sm">
                + new cohort
            </Link>
            <br />
            <br />
            <Table
                size="small"
                columns={columns}
                loading={cohortsLoading}
                rowKey={cohort => cohort.id}
                pagination={{ pageSize: 100, hideOnSinglePage: true }}
                dataSource={cohorts}
            />
        </div>
    )
}
