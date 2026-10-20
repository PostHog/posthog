import { useActions } from 'kea'

import { SceneMenuBarItem, SceneMenuBarSubMenu } from '~/layout/scenes/components/SceneMenuBar'

import { getDashboardAddTileOptions } from './dashboardAddTileOptions'
import { dashboardLogic } from './dashboardLogic'

export function DashboardAddTileSubMenu(): JSX.Element {
    const { openAddInsightModal, openTextTileModal, openImageTileModal, openButtonTileModal, setAddWidgetModalOpen } =
        useActions(dashboardLogic)

    const options = getDashboardAddTileOptions({
        onAddInsight: openAddInsightModal,
        onAddText: openTextTileModal,
        onAddImage: openImageTileModal,
        onAddButton: openButtonTileModal,
        setAddWidgetModalOpen,
    })

    return (
        <SceneMenuBarSubMenu label="Add">
            {options.map((option) => (
                <SceneMenuBarItem
                    key={option.key}
                    opensFloatingUi
                    tooltip={option.tooltip}
                    onClick={option.onClick}
                    data-attr={`dashboard-menubar-add-${option.key}`}
                >
                    {option.label}
                </SceneMenuBarItem>
            ))}
        </SceneMenuBarSubMenu>
    )
}
