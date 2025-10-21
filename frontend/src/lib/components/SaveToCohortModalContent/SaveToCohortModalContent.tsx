import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { ActorsQuery } from '~/queries/schema/schema-general'
import { CohortType } from '~/types'

import { saveToCohortModalContentLogic } from './saveToCohortModalContentLogic'

interface SaveToCohortModalContentProps {
    closeModal: () => void
    query: ActorsQuery
}

export function SaveToCohortModalContent({ closeModal, query }: SaveToCohortModalContentProps): JSX.Element {
    const { cohorts, cohortsLoading, pagination, cohortFilters } = useValues(saveToCohortModalContentLogic)
    const { setCohortFilters, saveQueryToCohort } = useActions(saveToCohortModalContentLogic)

    const columns: LemonTableColumns<CohortType> = [
        {
            title: 'Name',
            dataIndex: 'name',
            sorter: (a, b) => (a.name || '').localeCompare(b.name || ''),
            render: function Render(name, { id, description }) {
                return (
                    <LemonTableLink
                        to={urls.cohort(id)}
                        target="_blank"
                        title={
                            name ? (
                                <>
                                    {name} <IconOpenInNew className="shrink-0" />
                                </>
                            ) : (
                                'Untitled'
                            )
                        }
                        description={description}
                    />
                )
            },
        },
        {
            title: null,
            render: function RenderActions(_, cohort) {
                return (
                    <LemonButton
                        size="xsmall"
                        type="primary"
                        onClick={() => {
                            saveQueryToCohort(cohort, query)
                            closeModal()
                        }}
                    >
                        Select
                    </LemonButton>
                )
            },
        },
    ]
    return (
        <div className="text-muted mb-2 w-160">
            <LemonInput
                className="w-48 mb-2"
                type="search"
                placeholder="Search for cohorts"
                onChange={(search) => {
                    setCohortFilters({ search: search || undefined, page: 1 })
                }}
                value={cohortFilters.search}
            />
            <LemonTable
                columns={columns}
                loading={cohortsLoading}
                rowKey="id"
                pagination={pagination}
                dataSource={cohorts.results}
                nouns={['cohort', 'cohorts']}
                data-attr="static-cohorts-table"
                useURLForSorting={false}
            />
        </div>
    )
}
