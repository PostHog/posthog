import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'

import { SceneMenuBarItem, SceneMenuBarSeparator, SceneMenuBarSubMenu } from '~/layout/scenes/components/SceneMenuBar'

import { getDashboardAddTileOptions, groupDashboardAddTileOptions } from './dashboardAddTileOptions'

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
        onAddGroup: tileGroupSectionsEnabled ? () => addTileGroup() : undefined,
    })

    return (
        <SceneMenuBarSubMenu label="Add">
            {groupDashboardAddTileOptions(options).map(({ section, options: sectionOptions }, index) => (
                <Fragment key={section}>
                    {index > 0 && <SceneMenuBarSeparator />}
                    {sectionOptions.map((option) => (
                        <SceneMenuBarItem
                            key={option.key}
                            opensFloatingUi
                            onClick={option.onClick}
                            data-attr={`dashboard-menubar-add-${option.key}`}
                        >
                            {option.label}
                        </SceneMenuBarItem>
                    ))}
                </Fragment>
            ))}
        </SceneMenuBarSubMenu>
    )
}
