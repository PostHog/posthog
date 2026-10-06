import { useActions, useValues } from 'kea'

import { LemonButton, LemonInput, LemonModal, LemonTable, LemonTableColumn } from '@posthog/lemon-ui'

import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTableLink } from 'lib/lemon-ui/LemonTable/LemonTableLink'

import { crossProjectDashboardsListLogic } from './crossProjectDashboardsListLogic'
import type { CrossProjectDashboardListItemApi } from './generated/api.schemas'

/** The list of cross-project dashboards, usable as a scene or as a tab on the dashboards page. The page header holds its "New" button. */
export function CrossProjectDashboardsList(): JSX.Element {
    const { dashboards, dashboardsLoading, isNewModalOpen, newName, isCreating } = useValues(
        crossProjectDashboardsListLogic
    )
    const { closeNewModal, setNewName, createDashboard, deleteDashboard } = useActions(crossProjectDashboardsListLogic)

    const columns: LemonTableColumn<
        CrossProjectDashboardListItemApi,
        keyof CrossProjectDashboardListItemApi | undefined
    >[] = [
        {
            title: 'Name',
            dataIndex: 'name',
            render: (_, dashboard) => (
                <LemonTableLink
                    to={`/cross-project-dashboards/${dashboard.id}`}
                    title={dashboard.name}
                    description={dashboard.description}
                />
            ),
        },
        {
            title: 'Projects',
            dataIndex: 'project_count',
        },
        {
            title: 'Tiles',
            dataIndex: 'tile_count',
        },
        {
            width: 48,
            render: (_, dashboard) => (
                <More
                    data-attr="cross-project-dashboard-list-more"
                    overlay={
                        <LemonButton
                            status="danger"
                            fullWidth
                            onClick={() => deleteDashboard(dashboard)}
                            data-attr="cross-project-dashboard-list-delete"
                        >
                            Delete dashboard
                        </LemonButton>
                    }
                />
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-4">
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
