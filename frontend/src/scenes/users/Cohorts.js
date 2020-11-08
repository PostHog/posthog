import React from 'react'
import { Link } from 'lib/components/Link'
import { LinkButton } from 'lib/components/LinkButton'
import moment from 'moment'
import { DeleteWithUndo } from 'lib/utils'
import { Tooltip, Table, Spin } from 'antd'
import { ExportOutlined, DeleteOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { cohortsModel } from '../../models/cohortsModel'
import { useValues, useActions } from 'kea'
import { hot } from 'react-hot-loader/root'
import rrwebBlockClass from 'lib/utils/rrwebBlockClass'
import { PageHeader } from 'lib/components/PageHeader'
import { PlusOutlined } from '@ant-design/icons'

export const Cohorts = hot(_Cohorts)
function _Cohorts() {
    const { cohorts, cohortsLoading } = useValues(cohortsModel)
    const { loadCohorts } = useActions(cohortsModel)
    let columns = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            render: function RenderName(_, cohort) {
                return (
                    <Link className={rrwebBlockClass} to={'/persons?cohort=' + cohort.id}>
                        {cohort.name}
                    </Link>
                )
            },
        },
        {
            title: 'Users in cohort',
            render: function RenderCount(_, cohort) {
                return cohort.count.toLocaleString()
            },
        },
        {
            title: 'Created at',
            render: function RenderCreatedAt(_, cohort) {
                return cohort.created_at ? moment(cohort.created_at).format('LLL') : '-'
            },
        },
        {
            title: 'Created by',
            render: function RenderCreatedBy(_, cohort) {
                return cohort.created_by ? cohort.created_by.first_name || cohort.created_by.email : '-'
            },
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
            render: function RenderCalculation(_, cohort) {
                return cohort.is_calculating ? (
                    <span>
                        Calculating <Spin />
                    </span>
                ) : (
                    moment(cohort.last_calculation).fromNow()
                )
            },
        },
        {
            title: 'Actions',
            render: function RenderActions(cohort) {
                return (
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
                )
            },
        },
    ]

    return (
        <div>
            <PageHeader
                title="Cohorts"
                caption="Create lists of users who have something in common to use in analytics or feature flags."
            />
            <div>
                <div className="mb text-right">
                    <LinkButton to={'/cohorts/new'} type="primary" data-attr="create-cohort" icon={<PlusOutlined />}>
                        New Cohort
                    </LinkButton>
                </div>

                <Table
                    size="small"
                    columns={columns}
                    loading={!cohorts && cohortsLoading}
                    rowKey={(cohort) => cohort.id}
                    pagination={{ pageSize: 100, hideOnSinglePage: true }}
                    dataSource={cohorts}
                />
            </div>
        </div>
    )
}
