import { useActions, useValues } from 'kea'

import { SceneMenuBarItem, SceneMenuBarSubMenu } from '~/layout/scenes/components/SceneMenuBar'

import { openAddTileGroupDialog } from 'products/dashboards/frontend/components/DashboardTileGroup/DashboardTileGroupMenu'

import { getDashboardAddTileOptions } from './dashboardAddTileOptions'
import { dashboardLogic } from './dashboardLogic'

export function DashboardAddTileSubMenu(): JSX.Element {
    const { tileGroupSectionsEnabled } = useValues(dashboardLogic)
    const {
        openAddInsightModal,
        openTextTileModal,
        openImageTileModal,
        openButtonTileModal,
        setAddWidgetModalOpen,
        addTileGroup,
    } = useActions(dashboardLogic)

    const options = getDashboardAddTileOptions({
        onAddInsight: openAddInsightModal,
        onAddText: openTextTileModal,
        onAddImage: openImageTileModal,
        onAddButton: openButtonTileModal,
        setAddWidgetModalOpen,
        onAddGroup: tileGroupSectionsEnabled ? () => openAddTileGroupDialog(addTileGroup) : undefined,
    })

    return (
        <SceneMenuBarSubMenu label="Add">
            {options.map((option) => (
                <SceneMenuBarItem
                    key={option.key}
                    opensFloatingUi
                    onClick={option.onClick}
                    data-attr={`dashboard-menubar-add-${option.key}`}
                >
                    {option.label}
                </SceneMenuBarItem>
            ))}
        </SceneMenuBarSubMenu>
    )
}
