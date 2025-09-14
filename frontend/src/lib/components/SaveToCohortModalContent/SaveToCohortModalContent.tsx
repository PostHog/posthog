import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { urls } from 'scenes/urls'

import { CohortType } from '~/types'

import { saveToCohortModalContentLogic } from './saveToCohortModalContentLogic'

export function SaveToCohortModalContent(): JSX.Element {
    const { cohorts, cohortsLoading, pagination, cohortFilters } = useValues(saveToCohortModalContentLogic)
    const { setCohortFilters } = useActions(saveToCohortModalContentLogic)

    const columns: LemonTableColumns<CohortType> = [
        {
            title: 'Name',
            dataIndex: 'name',
            sorter: (a, b) => (a.name || '').localeCompare(b.name || ''),
            render: function Render(name, { id, description }) {
                return (
                    <>
                        <LemonTableLink
                            to={urls.cohort(id)}
                            title={name ? <>{name}</> : 'Untitled'}
                            description={description}
                        />
                    </>
                )
            },
        },
        {
            title: null,
            render: function RenderActions(_, cohort) {
                return (
                    <LemonButton size="xsmall" type="primary" onClick={() => {}}>
                        Select
                    </LemonButton>
                )
            },
        },
    ]
    return (
        <div className="text-muted mb-2 w-160">
            <div className="flex justify-between gap-2 flex-wrap">
                <LemonInput
                    className="w-48"
                    type="search"
                    placeholder="Search for cohorts"
                    onChange={(search) => {
                        setCohortFilters({ search: search || undefined, page: 1 })
                    }}
                    value={cohortFilters.search}
                />
            </div>
            <LemonTable
                columns={columns}
                loading={cohortsLoading}
                rowKey="id"
                pagination={pagination}
                dataSource={cohorts.results}
                nouns={['cohort', 'cohorts']}
                data-attr="static-cohorts-table"
            />
        </div>
    )
}
