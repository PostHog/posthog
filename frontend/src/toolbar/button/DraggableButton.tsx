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
import { Stats } from '~/toolbar/button/icons/Stats'
import { posthog } from '~/toolbar/posthog'

export function DraggableButton(): JSX.Element {
    const {
        dragPosition,
        heatmapPosition,
        heatmapWindowVisible,
        actionsWindowVisible,
        actionsPosition,
        statsVisible,
        statsPosition,
    } = useValues(toolbarButtonLogic)
    const {
        saveDragPosition,
        saveHeatmapPosition,
        saveActionsPosition,
        hideActionsInfo,
        hideHeatmapInfo,
        hideStats,
        saveStatsPosition,
    } = useActions(toolbarButtonLogic)

    return (
        <>
            <Draggable
                handle=".floating-toolbar-button"
                position={dragPosition}
                onDrag={(_, { x, y }) => {
                    saveDragPosition(x, y)
                }}
                onStop={(_, { x, y }) => {
                    posthog.capture('toolbar dragged', { x, y })
                    saveDragPosition(x, y)
                }}
            >
                <div id="button-toolbar" className="ph-no-capture">
                    <ToolbarButton />
                </div>
            </Draggable>

            <ButtonWindow
                name="heatmap"
                label="Heatmap"
                icon={<Fire engaged />}
                visible={heatmapWindowVisible}
                close={hideHeatmapInfo}
                position={heatmapPosition}
                savePosition={saveHeatmapPosition}
            >
                <div className="toolbar-block">
                    <HeatmapStats buttonMode />
                </div>
            </ButtonWindow>

            <ButtonWindow
                name="actions"
                label="Actions"
                icon={<Flag engaged />}
                visible={actionsWindowVisible}
                close={hideActionsInfo}
                position={actionsPosition}
                savePosition={saveActionsPosition}
            >
                <ActionsTab />
            </ButtonWindow>

            <ButtonWindow
                name="stats"
                label="Stats"
                icon={<Stats />}
                visible={statsVisible}
                close={hideStats}
                position={statsPosition}
                savePosition={saveStatsPosition}
            >
                <div className="toolbar-block">
                    <p>Thank you for trying out the PostHog Toolbar!</p>
                    <p>The stats view is coming soon!</p>
                    <p>
                        Follow the{' '}
                        <a
                            href="https://github.com/PostHog/posthog/projects/7"
                            target="_blank"
                            rel="noopener noreferrer"
                        >
                            Toolbar Project
                        </a>{' '}
                        and the{' '}
                        <a
                            href="https://github.com/PostHog/posthog/issues/871"
                            target="_blank"
                            rel="noopener noreferrer"
                        >
                            stats issue
                        </a>{' '}
                        on GitHub to stay up to date with the releases!
                    </p>
                    <p>
                        <strong>
                            To ask questions and to provide feedback during the beta program, please{' '}
                            <a
                                href="https://github.com/PostHog/posthog/issues/1129"
                                target="_blank"
                                rel="noreferrer noopener"
                            >
                                click here
                            </a>
                            !
                        </strong>
                    </p>
                </div>
            </ButtonWindow>
        </>
    )
}
