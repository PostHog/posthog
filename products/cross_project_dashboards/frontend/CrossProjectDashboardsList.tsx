import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonTable, LemonTableColumn } from '@posthog/lemon-ui'

import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'

import { crossProjectDashboardsListLogic } from './crossProjectDashboardsListLogic'
import type { CrossProjectDashboardApi } from './generated/api.schemas'

/** The list of cross-project dashboards, usable as a scene or as a tab on the dashboards page. */
export function CrossProjectDashboardsList(): JSX.Element {
    const { dashboards, dashboardsLoading, isNewModalOpen, newName, isCreating } = useValues(
        crossProjectDashboardsListLogic
    )
    const { openNewModal, closeNewModal, setNewName, createDashboard } = useActions(crossProjectDashboardsListLogic)

    const columns: LemonTableColumn<CrossProjectDashboardApi, keyof CrossProjectDashboardApi | undefined>[] = [
        {
            title: 'Name',
            dataIndex: 'name',
            render: (_, dashboard) => (
                <LemonTableLink to={`/cross-project-dashboards/${dashboard.id}`} title={dashboard.name} />
            ),
        },
        {
            title: 'Projects',
            render: (_, dashboard) => new Set((dashboard.tiles ?? []).map((tile) => tile.project_id)).size,
        },
        {
            title: 'Tiles',
            render: (_, dashboard) => (dashboard.tiles ?? []).length,
        },
    ]

    return (
        <div className="flex flex-col gap-4">
            <div className="flex justify-end">
                <LemonButton
                    type="primary"
                    icon={<IconPlus />}
                    onClick={openNewModal}
                    data-attr="cross-project-dashboard-new"
                >
                    New cross-project dashboard
                </LemonButton>
            </div>
            <LemonTable
                dataSource={dashboards}
                columns={columns}
                loading={dashboardsLoading}
                data-attr="cross-project-dashboards-table"
                emptyState="No cross-project dashboards yet. Create one to put insights from several projects on one page."
            />
            <LemonModal
                isOpen={isNewModalOpen}
                onClose={closeNewModal}
                title="New cross-project dashboard"
                footer={
                    <>
                        <LemonButton type="secondary" onClick={closeNewModal}>
                            Cancel
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={createDashboard}
                            disabledReason={!newName.trim() ? 'Give the dashboard a name first' : undefined}
                            loading={isCreating}
                            data-attr="cross-project-dashboard-new-confirm"
                        >
                            Create
                        </LemonButton>
                    </>
                }
            >
                <LemonInput
                    value={newName}
                    onChange={setNewName}
                    placeholder="Company overview"
                    autoFocus
                    data-attr="cross-project-dashboard-new-name"
                />
            </LemonModal>
        </div>
    )
}
