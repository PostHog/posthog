import { useActions, useValues } from 'kea'

import { IconFlask, IconPlus } from '@posthog/icons'
import { LemonInput, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'

import { getExperimentStatus } from '~/scenes/experiments/experimentsLogic'
import { StatusTag } from '~/scenes/experiments/ExperimentView/StatusTag'
import { Experiment } from '~/types'

import { addExperimentsToNotebookModalLogic } from './addExperimentsToNotebookModalLogic'

type ExperimentsNotebookTableProps = {
    onSelect: (experimentId: number) => void
}

export function ExperimentsNotebookTable({ onSelect }: ExperimentsNotebookTableProps): JSX.Element {
    const { experiments, experimentsLoading, filters, sorting, experimentsPerPage, count, modalPage } = useValues(
        addExperimentsToNotebookModalLogic
    )
    const { setModalPage, setModalFilters } = useActions(addExperimentsToNotebookModalLogic)

    const columns: LemonTableColumns<Experiment> = [
        {
            key: 'id',
            width: 32,
            render: function renderIcon() {
                return <IconFlask className="text-secondary text-2xl" />
            },
        },
        {
            title: 'Name',
            dataIndex: 'name',
            key: 'name',
            width: 300,
            render: function renderName(_, experiment: Experiment) {
                return (
                    <div className="flex flex-col gap-1 min-w-0 max-w-[300px] overflow-hidden">
                        <div className="flex items-center gap-1 min-w-0 overflow-hidden">
                            <Tooltip title={experiment.name}>
                                <span className="block truncate max-w-full font-medium">{experiment.name}</span>
                            </Tooltip>
                            {experiment.is_legacy && (
                                <LemonTag type="warning" size="small">
                                    Legacy
                                </LemonTag>
                            )}
                        </div>
                        {experiment.description && (
                            <Tooltip title={experiment.description}>
                                <div className="text-xs text-tertiary line-clamp-2">{experiment.description}</div>
                            </Tooltip>
                        )}
                    </div>
                )
            },
        },
        {
            title: 'Status',
            key: 'status',
            width: 100,
            render: function renderStatus(_: unknown, experiment: Experiment) {
                return <StatusTag status={getExperimentStatus(experiment)} />
            },
        },
        createdByColumn() as LemonTableColumn<Experiment, keyof Experiment | undefined>,
        {
            title: 'Created',
            sorter: true,
            dataIndex: 'created_at',
            width: 0,
            render: function renderCreatedAt(_, experiment: Experiment) {
                return (
                    <div className="whitespace-nowrap">
                        {experiment.created_at && <TZLabel time={experiment.created_at} />}
                    </div>
                )
            },
        },
        {
            key: 'action',
            width: 32,
            render: function renderAction() {
                return (
                    <IconPlus className="text-muted text-xl opacity-40 group-hover:opacity-100 group-hover:text-success transition-all" />
                )
            },
        },
    ]

    return (
        <div className="experiments-notebook-table">
            <div className="mb-3">
                <LemonInput
                    type="search"
                    placeholder="Search experiments"
                    onChange={(search) => setModalFilters({ search, page: 1 })}
                    value={filters.search || ''}
                />
            </div>
            <div className="overflow-x-hidden">
                <LemonTable
                    dataSource={experiments.results}
                    columns={columns}
                    loading={experimentsLoading}
                    pagination={{
                        controlled: true,
                        currentPage: modalPage,
                        pageSize: experimentsPerPage,
                        entryCount: count,
                        onForward: () => setModalPage(modalPage + 1),
                        onBackward: () => setModalPage(modalPage - 1),
                    }}
                    sorting={sorting}
                    onSort={(newSorting) =>
                        setModalFilters({
                            order: newSorting
                                ? `${newSorting.order === -1 ? '-' : ''}${newSorting.columnKey}`
                                : undefined,
                        })
                    }
                    rowKey="id"
                    loadingSkeletonRows={experimentsPerPage}
                    nouns={['experiment', 'experiments']}
                    rowClassName={() =>
                        'group cursor-pointer hover:bg-success-highlight/30 border-l-2 border-l-transparent hover:border-l-success/50'
                    }
                    onRow={(experiment) => ({
                        onClick: () => onSelect(experiment.id as number),
                        title: 'Click to select',
                    })}
                    emptyState="No experiments found"
                />
            </div>
        </div>
    )
}
