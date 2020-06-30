import React from 'react'
import { ToolbarButton } from '~/toolbar/button/ToolbarButton'
import Draggable from 'react-draggable'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import { useActions, useValues } from 'kea'
import { HeatmapStats } from '~/toolbar/stats/HeatmapStats'
import { Fire } from '~/toolbar/button/icons/Fire'
import { Flag } from '~/toolbar/button/icons/Flag'
import { ActionsTab } from '~/toolbar/actions/ActionsTab'
import { ButtonWindow } from '~/toolbar/button/ButtonWindow'

export function DraggableButton({ showInvisibleButton }) {
    const { dragPosition, heatmapPosition, heatmapWindowVisible, actionsWindowVisible, actionsPosition } = useValues(
        toolbarButtonLogic
    )
    const { saveDragPosition, saveHeatmapPosition, saveActionsPosition, hideActionsInfo, hideHeatmapInfo } = useActions(
        toolbarButtonLogic
    )

    return (
        <>
            <Draggable
                handle="#button-toolbar"
                position={dragPosition}
                onDrag={(e, { x, y }) => saveDragPosition(x, y)}
                onStop={(e, { x, y }) => saveDragPosition(x, y)}
            >
                <div id="button-toolbar" className={showInvisibleButton ? 'toolbar-invisible' : ''}>
                    <ToolbarButton />
                </div>
            </Draggable>

            <ButtonWindow
                name="heatmap"
                label="Heatmap"
                icon={<Fire engaged style={{ height: 18 }} />}
                visible={heatmapWindowVisible}
                close={hideHeatmapInfo}
                position={heatmapPosition}
                savePosition={saveHeatmapPosition}
            >
                <HeatmapStats buttonMode />
            </ButtonWindow>

            <ButtonWindow
                name="actions"
                label="Actions"
                icon={<Flag engaged style={{ height: 18 }} />}
                visible={actionsWindowVisible}
                close={hideActionsInfo}
                position={actionsPosition}
                savePosition={saveActionsPosition}
            >
                <ActionsTab />
            </ButtonWindow>
        </>
    )
}
