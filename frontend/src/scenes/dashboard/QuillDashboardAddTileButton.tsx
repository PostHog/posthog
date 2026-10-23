import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import {
    Badge,
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { MaxTool } from 'scenes/max/MaxTool'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { DashboardAddTileKey, getDashboardAddTileOptions } from './dashboardAddTileOptions'
import { DashboardLoadAction, dashboardLogic } from './dashboardLogic'

// pinned: autocapture data-attrs for the header's Add menu items
const ADD_TILE_MENU_DATA_ATTRS: Record<DashboardAddTileKey, string> = {
    insight: 'dashboard-add-insight',
    text: 'dashboard-add-text-tile',
    image: 'dashboard-add-image-tile',
    button: 'dashboard-add-button-tile',
    widget: 'dashboard-add-widget',
}

export function QuillDashboardAddTileButton(): JSX.Element | null {
    const { dashboard, tiles } = useValues(dashboardLogic)
    const {
        loadDashboard,
        setAddWidgetModalOpen,
        openAddInsightModal,
        openTextTileModal,
        openImageTileModal,
        openButtonTileModal,
    } = useActions(dashboardLogic)
    const { reportDashboardAddMenuOpened } = useActions(eventUsageLogic)

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
                    <DropdownMenuContent align="end" className="min-w-40">
                        <DropdownMenuGroup>
                            <DropdownMenuLabel>Content</DropdownMenuLabel>
                            {options.map((option) => {
                                return (
                                    <DropdownMenuItem
                                        key={option.key}
                                        onClick={option.onClick}
                                        data-attr={ADD_TILE_MENU_DATA_ATTRS[option.key]}
                                    >
                                        {option.label}
                                        {option.tag && (
                                            <Badge variant="success" className="ml-auto">
                                                {option.tag.toUpperCase()}
                                            </Badge>
                                        )}
                                    </DropdownMenuItem>
                                )
                            })}
                        </DropdownMenuGroup>
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
        </MaxTool>
    )
}
