import React, { useEffect } from 'react'
import { useActions, useValues } from 'kea'
import { personsLogic } from './personsLogic'
import { CohortType } from '~/types'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { urls } from 'scenes/urls'
import { Link } from 'lib/components/Link'

export function PersonCohorts(): JSX.Element {
    const { cohorts, cohortsLoading, person } = useValues(personsLogic)
    const { loadCohorts } = useActions(personsLogic)

    useEffect(() => {
        loadCohorts()
    }, [person])

    const columns: LemonTableColumns<CohortType> = [
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            className: 'ph-no-capture',
            render: function RenderName(_, cohort) {
                return (
                    <Link to={urls.cohort(cohort.id)}>
                        <strong>{cohort.name}</strong>
                    </Link>
                )
            },
            sorter: (a, b) => (a.name || '').localeCompare(b.name || ''),
        },
        {
            title: 'Users in cohort',
            render: function RenderCount(count) {
                return (count as number)?.toLocaleString()
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
            rowKey="id"
            pagination={{ pageSize: 30, hideOnSinglePage: true }}
            emptyState="This person doesn't belong to any cohort"
        />
    )
}
