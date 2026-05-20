import { useActions, useValues } from 'kea'

import { IconCheck, IconFlask, IconPlus, IconX } from '@posthog/icons'
import { LemonInput, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumn, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'

import { getExperimentStatus } from '~/scenes/experiments/experimentsLogic'
import { StatusTag } from '~/scenes/experiments/ExperimentView/components'
import { isLegacyExperiment } from '~/scenes/experiments/utils'
import { notebookLogic } from '~/scenes/notebooks/Notebook/notebookLogic'
import { NotebookNodeType } from '~/scenes/notebooks/types'
import { Experiment } from '~/types'

import { addExperimentsToNotebookModalLogic } from './addExperimentsToNotebookModalLogic'

type ExperimentsNotebookTableProps = {
    insertionPosition: number | null
}

export function ExperimentsNotebookTable({ insertionPosition }: ExperimentsNotebookTableProps): JSX.Element {
    const { experiments, experimentsLoading, filters, sorting, experimentsPerPage, count, modalPage } = useValues(
        addExperimentsToNotebookModalLogic
    )
    const { setModalPage, setModalFilters, closeModal } = useActions(addExperimentsToNotebookModalLogic)

    const { experimentIdsInNotebook, findNodeLogic } = useValues(notebookLogic)
    const { addExperimentToNotebook } = useActions(notebookLogic)

    const isSelected = (experiment: Experiment): boolean => {
        return experimentIdsInNotebook?.includes(experiment.id as number) ?? false
    }

    const onToggle = (experiment: Experiment): void => {
        // If already in notebook, remove it
        if (isSelected(experiment)) {
            const nodeLogic = findNodeLogic(NotebookNodeType.Experiment, { id: experiment.id })
            if (nodeLogic) {
                nodeLogic.actions.deleteNode()
            }
            return
        }

        addExperimentToNotebook(experiment.id as number, insertionPosition)
        closeModal()
    }

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
                            {isLegacyExperiment(experiment) && (
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
            render: function renderAction(_: unknown, experiment: Experiment) {
                return isSelected(experiment) ? (
                    <div className="group/status relative flex items-center justify-center">
                        <IconCheck className="text-success text-xl transition-opacity duration-150 group-hover/status:opacity-0" />
                        <IconX className="text-danger text-xl absolute inset-0 opacity-0 transition-opacity duration-150 group-hover/status:opacity-100" />
                    </div>
                ) : (
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
                    rowClassName={(experiment) =>
                        isSelected(experiment)
                            ? 'group bg-success-highlight border-l-2 border-l-success cursor-pointer hover:bg-success-highlight/70'
                            : 'group cursor-pointer hover:bg-success-highlight/30 border-l-2 border-l-transparent hover:border-l-success/50'
                    }
                    onRow={(experiment) => ({
                        onClick: () => onToggle(experiment),
                        title: isSelected(experiment) ? 'Click to deselect' : 'Click to select',
                    })}
                    emptyState="No experiments found"
                />
            </div>
        </div>
    )
}
