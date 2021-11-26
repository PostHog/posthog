import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { personsLogic } from './personsLogic'
import Skeleton from 'antd/lib/skeleton'
import { CohortType } from '~/types'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable/LemonTable'

export function PersonCohorts(): JSX.Element {
    const { cohorts, cohortsLoading } = useValues(personsLogic)
    const { loadCohorts, navigateToCohort } = useActions(personsLogic)

    useEffect(() => {
        if (cohorts === null && !cohortsLoading) {
            loadCohorts()
        }
    }, [cohorts, cohortsLoading])

    if (cohortsLoading) {
        return <Skeleton paragraph={{ rows: 2 }} active />
    }

    const columns: LemonTableColumns<CohortType> = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            className: 'ph-no-capture',
            sorter: (a, b) => (a.name || '').localeCompare(b.name || ''),
        },
        {
            title: 'Users in cohort',
            render: function RenderCount(count) {
                return (count as number).toLocaleString()
            },
            dataIndex: 'count',
            sorter: (a, b) => (a.count || 0) - (b.count || 0),
        },
    ]

    return (
        <LemonTable
            dataSource={cohorts || []}
            loading={cohortsLoading}
            columns={columns}
            rowClassName="cursor-pointer"
            rowKey="id"
            pagination={{ pageSize: 20, hideOnSinglePage: true }}
            embedded
            onRow={(cohort) => ({
                onClick: () => navigateToCohort(cohort),
            })}
            emptyState="This person doesn't belong to any cohort"
        />
    )
}
