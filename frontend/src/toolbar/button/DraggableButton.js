import React from 'react'
import { ToolbarButton } from '~/toolbar/button/ToolbarButton'
import Draggable from 'react-draggable'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import { useActions, useValues } from 'kea'
import { Fade } from 'lib/components/Fade/Fade'
import { HeatmapStats } from '~/toolbar/stats/HeatmapStats'
import { Fire } from '~/toolbar/button/icons/Fire'
import { Flag } from '~/toolbar/button/icons/Flag'
import { ActionsTab } from '~/toolbar/actions/ActionsTab'

export function DraggableButton({ showInvisibleButton }) {
    const { dragPosition, heatmapPosition, heatmapWindowVisible, actionsWindowVisible, actionsPosition } = useValues(
        toolbarButtonLogic
    )
    const { saveDragPosition, saveHeatmapPosition, saveActionsPosition } = useActions(toolbarButtonLogic)

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

            <Fade visible={heatmapWindowVisible}>
                <Draggable
                    handle=".toolbar-info-window-title"
                    position={heatmapPosition}
                    onDrag={(e, { x, y }) => saveHeatmapPosition(x, y)}
                    onStop={(e, { x, y }) => saveHeatmapPosition(x, y)}
                >
                    <div className="toolbar-info-windows heatmap-button-window">
                        <div className="toolbar-info-window-title">
                            <Fire engaged style={{ height: 18 }} />
                            <span>Heatmap</span>{' '}
                        </div>
                        <HeatmapStats buttonMode />
                    </div>
                </Draggable>
            </Fade>

            <Fade visible={actionsWindowVisible}>
                <Draggable
                    handle=".toolbar-info-window-title"
                    position={actionsPosition}
                    onDrag={(e, { x, y }) => saveActionsPosition(x, y)}
                    onStop={(e, { x, y }) => saveActionsPosition(x, y)}
                >
                    <div className="toolbar-info-windows actions-button-window">
                        <div className="toolbar-info-window-title">
                            <Flag engaged style={{ height: 18 }} />
                            <span>Actions</span>{' '}
                        </div>
                        <ActionsTab />
                    </div>
                </Draggable>
            </Fade>
        </>
    )
}
