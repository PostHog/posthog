import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { personsLogic } from './personsLogic'
import Skeleton from 'antd/lib/skeleton'
import { Table } from 'antd'
import { CohortType } from '~/types'

export function PersonCohorts(): JSX.Element {
    const { cohorts, cohortsLoading } = useValues(personsLogic)
    const { loadCohorts, navigateToCohort } = useActions(personsLogic)

    useEffect(
        () => {
            if (cohorts === null && !cohortsLoading) {
                loadCohorts()
            }
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [cohorts, cohortsLoading]
    )

    if (cohortsLoading) {
        return <Skeleton paragraph={{ rows: 2 }} active />
    }

    const columns = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            className: 'ph-no-capture',
            sorter: (a: CohortType, b: CohortType) => ('' + a.name).localeCompare(b.name as string),
        },
        {
            title: 'Users in cohort',
            render: function RenderCount(_: any, cohort: CohortType) {
                return cohort.count?.toLocaleString()
            },
            sorter: (a: CohortType, b: CohortType) => (a.count || 0) - (b.count || 0),
        },
    ]

    return (
        <Table
            dataSource={cohorts || []}
            loading={cohortsLoading}
            columns={columns}
            rowClassName="cursor-pointer"
            rowKey="id"
            pagination={{ pageSize: 100, hideOnSinglePage: true }}
            onRow={(cohort) => ({
                onClick: () => navigateToCohort(cohort),
                'data-test-cohort-row': cohort.id,
            })}
            locale={{ emptyText: 'Person belongs to no cohorts' }}
        />
    )
}
