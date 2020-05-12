import React, { Component } from 'react'
import { Link } from 'lib/components/Link'
import { LinkButton } from 'lib/components/LinkButton'
import moment from 'moment'
import { DeleteWithUndo } from 'lib/utils'
import { Tooltip, Table, Spin } from 'antd'
import { ExportOutlined, DeleteOutlined, InfoCircleOutlined } from '@ant-design/icons'
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
            title: 'Users in cohort',
            render: (_, cohort) => cohort.count.toLocaleString(),
        },
        {
            title: 'Created at',
            render: (_, cohort) => (cohort.created_at ? moment(cohort.created_at).format('LLL') : '-'),
        },
        {
            title: 'Created by',
            render: (_, cohort) => (cohort.created_by ? cohort.created_by.first_name || cohort.created_by.email : '-'),
        },
        {
            title: (
                <span>
                    <Tooltip title="PostHog calculates what users belong to each cohort. This is then used when filtering on cohorts in the Trends page etc. Calculating happens every 15 minutes, or whenever a cohort is updated.">
                        Last calculation
                        <InfoCircleOutlined style={{ marginLeft: 6 }} />
                    </Tooltip>
                </span>
            ),
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
            <LinkButton to={'/people/new_cohort'} type="primary">
                + new cohort
            </LinkButton>
            <br />
            <br />
            <Table
                size="small"
                columns={columns}
                loading={!cohorts && cohortsLoading}
                rowKey={cohort => cohort.id}
                pagination={{ pageSize: 100, hideOnSinglePage: true }}
                dataSource={cohorts}
            />
        </div>
    )
}
