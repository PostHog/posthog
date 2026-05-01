import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonInput, LemonModal, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'

import type { SavedTicketView, TicketViewFilters } from '../../types'
import { type TicketViewsLogicProps, ticketViewsLogic } from './ticketViewsLogic'

function FiltersSummary({ filters }: { filters: TicketViewFilters }): JSX.Element {
    const lines: { label: string; value: string }[] = []

    if (filters.status?.length) {
        lines.push({ label: 'Status', value: filters.status.join(', ') })
    }
    if (filters.priority?.length) {
        lines.push({ label: 'Priority', value: filters.priority.join(', ') })
    }
    if (filters.channel && filters.channel !== 'all') {
        lines.push({ label: 'Channel', value: filters.channel })
    }
    if (filters.sla && filters.sla !== 'all') {
        lines.push({ label: 'SLA', value: filters.sla })
    }
    if (filters.tags?.length) {
        lines.push({ label: 'Tags', value: filters.tags.join(', ') })
    }
    if (filters.assignee && filters.assignee !== 'all') {
        const val =
            filters.assignee === 'unassigned'
                ? 'Unassigned'
                : typeof filters.assignee === 'object'
                  ? `${filters.assignee.type}:${filters.assignee.id}`
                  : String(filters.assignee)
        lines.push({ label: 'Assignee', value: val })
    }
    if (filters.dateFrom) {
        lines.push({ label: 'Date from', value: filters.dateFrom })
    }

    if (lines.length === 0) {
        return <span className="text-muted text-xs">No filters</span>
    }
    return (
        <div className="text-xs text-muted space-y-0.5">
            {lines.map((line) => (
                <div key={line.label}>
                    <span className="font-medium">{line.label}:</span> {line.value}
                </div>
            ))}
        </div>
    )
}

function SaveViewModal({ id }: TicketViewsLogicProps): JSX.Element {
    const { isSaveModalOpen, viewName, currentFilters } = useValues(ticketViewsLogic({ id }))
    const { closeSaveModal, setViewName, saveView } = useActions(ticketViewsLogic({ id }))

    return (
        <LemonModal
            isOpen={isSaveModalOpen}
            onClose={closeSaveModal}
            title="Save current view"
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeSaveModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={saveView}
                        disabledReason={!viewName.trim() ? 'Enter a name' : undefined}
                    >
                        Save view
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-2">
                <LemonInput
                    placeholder="View name"
                    value={viewName}
                    onChange={setViewName}
                    autoFocus
                    onPressEnter={saveView}
                />
                <FiltersSummary filters={currentFilters} />
            </div>
        </LemonModal>
    )
}

export function SavedViewsModal({ id }: TicketViewsLogicProps): JSX.Element {
    const { isModalOpen, views, viewsLoading } = useValues(ticketViewsLogic({ id }))
    const { closeModal, openSaveModal, deleteView, loadView } = useActions(ticketViewsLogic({ id }))

    const columns: LemonTableColumns<SavedTicketView> = [
        {
            title: 'Name',
            dataIndex: 'name',
            render: (_, view) => <span className="font-medium">{view.name}</span>,
        },
        {
            title: 'Filters',
            render: (_, view) => <FiltersSummary filters={view.filters ?? {}} />,
        },
        {
            title: 'Created by',
            dataIndex: 'created_by',
            render: (_, view) => (
                <span className="text-muted text-xs">
                    {view.created_by?.first_name || view.created_by?.email || '\u2014'}
                </span>
            ),
        },
        {
            title: 'Created',
            dataIndex: 'created_at',
            render: (_, view) => <TZLabel time={view.created_at} />,
        },
        {
            title: '',
            render: (_, view) => (
                <div className="flex items-center gap-1">
                    <LemonButton type="secondary" size="xsmall" onClick={() => loadView(view)}>
                        Load
                    </LemonButton>
                    <More
                        overlay={
                            <LemonMenuOverlay
                                items={[
                                    {
                                        label: 'Delete',
                                        status: 'danger',
                                        onClick: () => {
                                            LemonDialog.open({
                                                title: `Delete "${view.name}"?`,
                                                description:
                                                    'This view will be permanently deleted. This action cannot be undone.',
                                                primaryButton: {
                                                    children: 'Delete',
                                                    type: 'primary',
                                                    status: 'danger',
                                                    onClick: () => deleteView(view.short_id),
                                                },
                                                secondaryButton: {
                                                    children: 'Cancel',
                                                },
                                            })
                                        },
                                    },
                                ]}
                            />
                        }
                    />
                </div>
            ),
        },
    ]

    return (
        <>
            <LemonModal
                isOpen={isModalOpen}
                onClose={closeModal}
                title="Saved views"
                width={720}
                footer={
                    <div className="flex justify-between w-full">
                        <LemonButton type="primary" onClick={openSaveModal}>
                            Save current view
                        </LemonButton>
                        <LemonButton type="secondary" onClick={closeModal}>
                            Close
                        </LemonButton>
                    </div>
                }
            >
                <LemonTable
                    columns={columns}
                    dataSource={views}
                    rowKey="id"
                    loading={viewsLoading}
                    emptyState="No saved views yet."
                    size="small"
                />
            </LemonModal>
            <SaveViewModal id={id} />
        </>
    )
}
