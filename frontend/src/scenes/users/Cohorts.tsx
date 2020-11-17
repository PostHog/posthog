import React, { useState } from 'react'
import { Link } from 'lib/components/Link'
import { LinkButton } from 'lib/components/LinkButton'
import moment from 'moment'
import { DeleteWithUndo } from 'lib/utils'
import { Tooltip, Table, Spin } from 'antd'
import { ExportOutlined, DeleteOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { cohortsModel } from '../../models/cohortsModel'
import { useValues, useActions, kea } from 'kea'
import { hot } from 'react-hot-loader/root'
import rrwebBlockClass from 'lib/utils/rrwebBlockClass'
import { PageHeader } from 'lib/components/PageHeader'
import { PlusOutlined } from '@ant-design/icons'
import { Created } from 'lib/components/Created'
import { Cohort } from './Cohort'
import { Drawer } from 'lib/components/Drawer'
import { CohortType } from '~/types'
import api from 'lib/api'

const cohortsUrlLogic = kea({
    actions: {
        setOpenCohort: (cohort: CohortType) => ({cohort})
    },
    reducers: {
        openCohort: [
            false,
            {
                setOpenCohort: (_, {cohort} : {cohort: CohortType}) => ({cohort})
            }
        ]
    },
    actionToUrl: ({ values }) => ({
        setOpenCohort: () => '/cohorts' + (values.openCohort ? '/' + (values.id || 'new') : ''),
    }),
    urlToAction: ({ actions, values }) => ({
        '/cohorts(/:cohortId)': async ({ cohortId }: Record<string, string>) => {
            if(cohortId && cohortId !== 'new' && cohortId !== values.openCohort.id) {
                const cohort = await api.get('cohort/' + cohortId);
                actions.setOpenCohort(cohort)
            }
        },
    }),
})

export const Cohorts = hot(_Cohorts)
function _Cohorts() {
    const { cohorts, cohortsLoading } = useValues(cohortsModel)
    const { loadCohorts } = useActions(cohortsModel)
    const { openCohort } = useValues(cohortsUrlLogic)
    const { setOpenCohort } = useActions(cohortsUrlLogic)

    let columns = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            sorter: (a: CohortType, b: CohortType) => ("" + a.name).localeCompare(b.name)
        },
        {
            title: 'Users in cohort',
            render: function RenderCount(_, cohort: CohortType) {
                return cohort.count?.toLocaleString()
            },
            sorter: (a: CohortType, b: CohortType) => a.count - b.count
        },
        {
            title: 'Created',
            render: function RenderCreatedAt(_, cohort: CohortType) {
                return cohort.created_at && <Created timestamp={cohort.created_at} />
            },
            sorter: (a: CohortType, b: CohortType) => moment(a.created_at).isAfter(b.created_at)
        },
        {
            title: 'Created by',
            render: function RenderCreatedBy(_, cohort: CohortType) {
                return cohort.created_by ? cohort.created_by.first_name || cohort.created_by.email : '-'
            },
            sorter: (a: CohortType, b: CohortType) => moment(a.created_by?.first_name).isAfter(b.created_by?.first_name)
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
            render: function RenderCalculation(_, cohort: CohortType) {
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
            render: function RenderActions(cohort: CohortType) {
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
                    <LinkButton to={'/cohorts/new#backTo=Cohorts&backToURL=/cohorts'} type="primary" data-attr="create-cohort" icon={<PlusOutlined />}>
                        New Cohort
                    </LinkButton>
                </div>

                <Table
                    size="small"
                    columns={columns}
                    loading={!cohorts && cohortsLoading}
                    rowKey={(cohort) => cohort.id}
                    pagination={{ pageSize: 100, hideOnSinglePage: true }}
                    onRow={(cohort) => ({
                        onClick: () => setOpenCohort(cohort),
                    })}
                    dataSource={cohorts}
                />
                <Drawer
                    title={openCohort.id === 'new' ? 'New cohort' : openCohort.name}
                    width={'80%'}
                    onClose={() => setOpenCohort(false)}
                    destroyOnClose={true}
                    visible={openCohort}
                >
                    {openCohort && <Cohort onChange={() => {}} cohort={openCohort} />}
                </Drawer>
            </div>
        </div>
    )
}
