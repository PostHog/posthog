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
import { HedgehogButton } from './HedgehogButton'

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
    } = useActions(toolbarButtonLogic)
    const { countFlagsOverridden } = useValues(featureFlagsLogic)

    // KLUDGE: if we put theme directly on the div then
    // linting and typescript complain about it not being
    // a valid attribute. So we put it in a variable and
    // spread it in. 🤷‍
    const themeProps = { theme: 'light' }

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
                {/*theme attribute and class posthog-3000 are set here
                so that everything inside is styled correctly
                without affecting hedgehog mode */}
                <div id="button-toolbar" className="ph-no-capture posthog-3000" {...themeProps}>
                    <ToolbarButton />
                </div>
            </Draggable>
            {hedgehogMode ? (
                <>
                    <HedgehogButton />
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
            ) : null}
        </>
    )
}
