import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuTrigger } from '@posthog/quill'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { reportDashboardAddMenuOpened } from 'scenes/dashboard/dashboardEvents'
import { DashboardLoadAction, dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { MaxTool } from 'scenes/max/MaxTool'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { getDashboardAddTileOptions } from './dashboardAddTileOptions'
import { QuillDashboardAddTileMenuContent } from './QuillDashboardAddTileMenuContent'

export function QuillDashboardAddTileButton(): JSX.Element | null {
    const { dashboard, tiles, tileGroupSectionsEnabled } = useValues(dashboardLogic)
    const {
        loadDashboard,
        setAddWidgetModalOpen,
        openAddInsightModal,
        openTextTileModal,
        openImageTileModal,
        openButtonTileModal,
        addTileGroup,
    } = useActions(dashboardLogic)

    if (!dashboard || tiles.length === 0) {
        return null
    }

    const disabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Dashboard,
        AccessControlLevel.Editor,
        dashboard.user_access_level
    )
    const options = getDashboardAddTileOptions({
        onAddInsight: openAddInsightModal,
        onAddText: openTextTileModal,
        onAddImage: openImageTileModal,
        onAddButton: openButtonTileModal,
        setAddWidgetModalOpen,
        onAddGroup: tileGroupSectionsEnabled ? () => addTileGroup() : undefined,
    })

    return (
        <MaxTool
            className="shrink-0"
            identifier="upsert_dashboard"
            context={{
                current_dashboard: {
                    id: dashboard.id,
                    name: dashboard.name,
                    description: dashboard.description,
                    tags: dashboard.tags,
                },
            }}
            contextDescription={{
                text: dashboard.name,
                icon: iconForType('dashboard'),
            }}
            active={false}
            callback={() => loadDashboard({ action: DashboardLoadAction.Update })}
            position="top-right"
        >
            {disabledReason ? (
                <Button variant="primary" data-attr="dashboard-add-tile" disabledReason={disabledReason}>
                    <IconPlus />
                    Add
                </Button>
            ) : (
                <DropdownMenu
                    onOpenChange={(open) => {
                        if (open) {
                            reportDashboardAddMenuOpened('header', dashboard.id)
                        }
                    }}
                >
                    <DropdownMenuTrigger render={<Button variant="primary" data-attr="dashboard-add-tile" />}>
                        <IconPlus />
                        Add
                    </DropdownMenuTrigger>
                    <QuillDashboardAddTileMenuContent options={options} align="end" />
                </DropdownMenu>
            )}
        </MaxTool>
    )
}
