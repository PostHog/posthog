import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog, LemonModal, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { useKeepMountedWhileOpen } from 'lib/hooks/useKeepMountedWhileOpen'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'

import { GetSavedViewFiltersSummaryLines, SavedViewFiltersSummary } from './SavedViewFiltersSummary'
import { SavedView, SavedViewPayload, SavedViewsLogicProps, savedViewsLogic } from './savedViewsLogic'
import { SaveViewModal } from './SaveViewModal'

interface SavedViewsModalProps {
    logicProps: SavedViewsLogicProps
    savePayload: SavedViewPayload
    getFiltersSummaryLines: GetSavedViewFiltersSummaryLines
}

export function SavedViewsModal({
    logicProps,
    savePayload,
    getFiltersSummaryLines,
}: SavedViewsModalProps): JSX.Element {
    const { isModalOpen, views, viewsLoading } = useValues(savedViewsLogic(logicProps))
    const { closeModal, openSaveModal, deleteView, loadView } = useActions(savedViewsLogic(logicProps))
    const shouldRenderList = useKeepMountedWhileOpen(isModalOpen)

    const columns: LemonTableColumns<SavedView> = [
        {
            title: 'Name',
            dataIndex: 'name',
            render: (_, view) => <span className="font-medium">{view.name}</span>,
        },
        {
            title: 'Filters',
            render: (_, view) => (
                <SavedViewFiltersSummary filters={view.filters ?? {}} getFiltersSummaryLines={getFiltersSummaryLines} />
            ),
        },
        {
            title: 'Created by',
            dataIndex: 'created_by',
            render: (_, view) => (
                <span className="text-muted text-xs">
                    {view.created_by?.first_name || view.created_by?.email || '—'}
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
            {shouldRenderList && (
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
            )}
            <SaveViewModal
                logicProps={logicProps}
                savePayload={savePayload}
                getFiltersSummaryLines={getFiltersSummaryLines}
            />
        </>
    )
}
