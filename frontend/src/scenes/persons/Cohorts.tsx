import React, { useState } from 'react'
import moment from 'moment'
import { DeleteWithUndo } from 'lib/utils'
import { Tooltip, Table, Spin, Button, Input } from 'antd'
import { ExportOutlined, DeleteOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { cohortsModel } from '../../models/cohortsModel'
import { useValues, useActions, kea } from 'kea'
import { hot } from 'react-hot-loader/root'
import { PageHeader } from 'lib/components/PageHeader'
import { PlusOutlined } from '@ant-design/icons'
import { Cohort } from './Cohort'
import { Drawer } from 'lib/components/Drawer'
import { CohortType } from '~/types'
import api from 'lib/api'
import rrwebBlockClass from 'lib/utils/rrwebBlockClass'
import './cohorts.scss'
import Fuse from 'fuse.js'
import { createdAtColumn, createdByColumn } from 'lib/components/Table'

const cohortsUrlLogic = kea({
    actions: {
        setOpenCohort: (cohort: CohortType) => ({ cohort }),
    },
    reducers: {
        openCohort: [
            false,
            {
                setOpenCohort: (_, { cohort }: { cohort: CohortType }) => cohort,
            },
        ],
    },
    actionToUrl: ({ values }) => ({
        setOpenCohort: () => '/cohorts' + (values.openCohort ? '/' + (values.openCohort.id || 'new') : ''),
    }),
    urlToAction: ({ actions, values }) => ({
        '/cohorts(/:cohortId)': async ({ cohortId }: Record<string, string>) => {
            if (cohortId && cohortId !== 'new' && cohortId !== values.openCohort.id) {
                const cohort = await api.get('api/cohort/' + cohortId)
                actions.setOpenCohort(cohort)
            }
        },
    }),
})

const searchCohorts = (sources: CohortType[], search: string): CohortType[] => {
    return new Fuse(sources, {
        keys: ['name'],
        threshold: 0.3,
    })
        .search(search)
        .map((result) => result.item)
}

export const Cohorts = hot(_Cohorts)
function _Cohorts(): JSX.Element {
    const { cohorts, cohortsLoading } = useValues(cohortsModel)
    const { loadCohorts } = useActions(cohortsModel)
    const { openCohort } = useValues(cohortsUrlLogic)
    const { setOpenCohort } = useActions(cohortsUrlLogic)
    const [searchTerm, setSearchTerm] = useState(false)

    const columns = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            sorter: (a: CohortType, b: CohortType) => ('' + a.name).localeCompare(b.name),
        },
        {
            title: 'Users in cohort',
            render: function RenderCount(_, cohort: CohortType) {
                return cohort.count?.toLocaleString()
            },
            sorter: (a: CohortType, b: CohortType) => a.count - b.count,
        },
        createdAtColumn(),
        createdByColumn(cohorts),
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
                <Input.Search
                    allowClear
                    enterButton
                    style={{ maxWidth: 400, width: 'initial', flexGrow: 1 }}
                    onChange={(e) => {
                        setSearchTerm(e.target.value)
                    }}
                />
                <div className="mb float-right">
                    <Button
                        type="primary"
                        data-attr="create-cohort"
                        onClick={() => setOpenCohort({ id: 'new', groups: [{}] })}
                        icon={<PlusOutlined />}
                    >
                        New Cohort
                    </Button>
                </div>

                <Table
                    size="small"
                    columns={columns}
                    loading={cohortsLoading}
                    rowKey="id"
                    pagination={{ pageSize: 100, hideOnSinglePage: true }}
                    rowClassName={'cursor-pointer ' + rrwebBlockClass}
                    onRow={(cohort) => ({
                        onClick: () => setOpenCohort(cohort),
                    })}
                    dataSource={searchTerm ? searchCohorts(cohorts, searchTerm) : cohorts}
                />
                <Drawer
                    title={openCohort.id === 'new' ? 'New cohort' : openCohort.name}
                    className="cohorts-drawer"
                    onClose={() => setOpenCohort(false)}
                    destroyOnClose={true}
                    visible={openCohort}
                >
                    {openCohort && <Cohort cohort={openCohort} />}
                </Drawer>
            </div>
        </div>
    )
}
