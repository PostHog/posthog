import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { SceneMenuBarItem, SceneMenuBarSubMenu } from '~/layout/scenes/components/SceneMenuBar'

import { getDashboardAddTileOptions } from './dashboardAddTileOptions'
import { dashboardLogic } from './dashboardLogic'

export function DashboardAddTileSubMenu(): JSX.Element {
    const { dashboardWidgetsEnabled } = useValues(dashboardLogic)
    const { openAddInsightModal, openTextTileModal, openImageTileModal, openButtonTileModal, setAddWidgetModalOpen } =
        useActions(dashboardLogic)
    const { push } = useActions(router)

    const options = getDashboardAddTileOptions({
        dashboardWidgetsEnabled,
        onAddInsight: openAddInsightModal,
        onAddText: openTextTileModal,
        onAddImage: openImageTileModal,
        onAddButton: openButtonTileModal,
        push,
        setAddWidgetModalOpen,
    })

    return (
        <SceneMenuBarSubMenu label="Add">
            {options.map((option) => (
                <SceneMenuBarItem
                    key={option.key}
                    // The beta widget link navigates to settings. Everything else opens a modal.
                    opensFloatingUi={option.key !== 'widget-preview'}
                    tooltip={option.tooltip}
                    onClick={option.onClick}
                    data-attr={`dashboard-menubar-add-${option.key}`}
                >
                    {option.tag === 'beta' ? `${option.label} (beta)` : option.label}
                </SceneMenuBarItem>
            ))}
        </SceneMenuBarSubMenu>
    )
}
