import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'

import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'

import { getDashboardAddTileOptions } from './dashboardAddTileOptions'

/** The "Add" submenu: one row per tile type the dashboard can take. */
export function useDashboardAddTileAction(): SceneAction {
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
        onAddGroup: tileGroupSectionsEnabled ? () => addTileGroup() : undefined,
    })

    return {
        group: 'file',
        section: 'tiles',
        type: 'submenu',
        id: 'dashboard-menubar-add',
        label: 'Add',
        icon: <IconPlusSmall />,
        items: options.map((option) => ({
            // pinned: data-attr values are wire strings
            id: `dashboard-menubar-add-${option.key}`,
            section: option.section,
            label: option.label,
            opensFloatingUi: option.key !== 'group',
            onSelect: option.onClick,
        })),
    }
}
