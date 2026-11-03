import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import {
    SceneMenuBar,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarSeparator,
} from '~/layout/scenes/components/SceneMenuBar'

import type { MetricSceneAction } from '../metricSceneActions'

export function MetricSceneMenuBar({ actions }: { actions: MetricSceneAction[] }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    const nonDestructive = actions.filter((action) => !action.destructive)
    const destructive = actions.filter((action) => action.destructive)

    return (
        <SceneMenuBar>
            <SceneMenuBarMenu label="Metric" dataAttr="data-catalog-metric-menubar">
                {nonDestructive.map((action) => (
                    <SceneMenuBarItem
                        key={action.key}
                        onClick={action.onClick}
                        disabled={!!action.disabledReason}
                        data-attr={`data-catalog-metric-menubar-${action.key}`}
                    >
                        {action.icon}
                        {action.label}
                    </SceneMenuBarItem>
                ))}
                <SceneMenuBarSeparator />
                {destructive.map((action) => (
                    <SceneMenuBarItem
                        key={action.key}
                        variant="destructive"
                        onClick={action.onClick}
                        data-attr={`data-catalog-metric-menubar-${action.key}`}
                    >
                        {action.icon}
                        {action.label}
                    </SceneMenuBarItem>
                ))}
            </SceneMenuBarMenu>
        </SceneMenuBar>
    )
}
