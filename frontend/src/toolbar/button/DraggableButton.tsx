import { ToolbarButton } from '~/toolbar/button/ToolbarButton'
import Draggable from 'react-draggable'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import { useActions, useValues } from 'kea'
import { HeatmapStats } from '~/toolbar/stats/HeatmapStats'
import { ActionsTab } from '~/toolbar/actions/ActionsTab'
import { ButtonWindow } from '~/toolbar/button/ButtonWindow'
import { posthog } from '~/toolbar/posthog'
import { FeatureFlags } from '~/toolbar/flags/FeatureFlags'
import { featureFlagsLogic } from '~/toolbar/flags/featureFlagsLogic'
import { HedgehogBuddy } from 'lib/components/HedgehogBuddy/HedgehogBuddy'
import { LemonButton } from '@posthog/lemon-ui'
import { heatmapLogic } from '../elements/heatmapLogic'
import { actionsTabLogic } from '../actions/actionsTabLogic'
import { elementsLogic } from '../elements/elementsLogic'

export function DraggableButton(): JSX.Element {
    const {
        dragPosition,
        heatmapPosition,
        heatmapWindowVisible,
        actionsWindowVisible,
        actionsPosition,
        flagsVisible,
        flagsPosition,
        hedgehogMode,
    } = useValues(toolbarButtonLogic)
    const {
        saveDragPosition,
        saveHeatmapPosition,
        saveActionsPosition,
        hideActionsInfo,
        hideHeatmapInfo,
        hideFlags,
        saveFlagsPosition,
        showFlags,
    } = useActions(toolbarButtonLogic)
    const { countFlagsOverridden } = useValues(featureFlagsLogic)

    const { enableHeatmap, disableHeatmap } = useActions(heatmapLogic)
    const { heatmapEnabled } = useValues(heatmapLogic)

    const { buttonActionsVisible } = useValues(actionsTabLogic)
    const { hideButtonActions, showButtonActions } = useActions(actionsTabLogic)

    const { enableInspect, disableInspect } = useActions(elementsLogic)
    const { inspectEnabled } = useValues(elementsLogic)

    return (
        <>
            {!hedgehogMode ? (
                <HedgehogBuddy
                    popoverOverlay={
                        <>
                            <LemonButton fullWidth onClick={() => (flagsVisible ? hideFlags() : showFlags())}>
                                Feature Flags
                            </LemonButton>
                            <LemonButton
                                fullWidth
                                onClick={() => (heatmapEnabled ? disableHeatmap() : enableHeatmap())}
                            >
                                Heatmap
                            </LemonButton>
                            <LemonButton
                                fullWidth
                                onClick={() => (buttonActionsVisible ? hideButtonActions() : showButtonActions())}
                            >
                                Actions
                            </LemonButton>
                            <LemonButton
                                fullWidth
                                onClick={() => (inspectEnabled ? disableInspect() : enableInspect())}
                            >
                                Inspect
                            </LemonButton>
                        </>
                    }
                    onClose={function (): void {
                        throw new Error('Function not implemented.')
                    }}
                />
            ) : (
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
            )}

            <ButtonWindow
                name="heatmap"
                label="Heatmap"
                visible={heatmapWindowVisible}
                close={hideHeatmapInfo}
                position={heatmapPosition}
                savePosition={saveHeatmapPosition}
            >
                <div className="toolbar-block">
                    <HeatmapStats />
                </div>
            </ButtonWindow>

            <ButtonWindow
                name={'actions'}
                label={'Actions'}
                visible={actionsWindowVisible}
                close={hideActionsInfo}
                position={actionsPosition}
                savePosition={saveActionsPosition}
            >
                <ActionsTab />
            </ButtonWindow>

            <ButtonWindow
                name="flags"
                label="Feature Flags"
                tagComponent={
                    countFlagsOverridden > 0 ? (
                        <span className="overridden-tag">{`${countFlagsOverridden} overridden`}</span>
                    ) : null
                }
                visible={flagsVisible}
                close={hideFlags}
                position={flagsPosition}
                savePosition={saveFlagsPosition}
            >
                <FeatureFlags />
            </ButtonWindow>
        </>
    )
}
