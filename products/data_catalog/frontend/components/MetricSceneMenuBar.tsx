import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import {
    SceneMenuBar,
    SceneMenuBarItem,
    SceneMenuBarMenu,
    SceneMenuBarSeparator,
} from '~/layout/scenes/components/SceneMenuBar'

import type { MetricSceneAction, MetricSceneMenu } from '../metricSceneActions'

const MENU_DATA_ATTR_PREFIX = 'data-catalog-metric-menubar'

function MetricMenuItem({ action }: { action: MetricSceneAction }): JSX.Element {
    return (
        <SceneMenuBarItem
            onClick={action.onClick}
            disabled={!!action.disabledReason}
            tooltip={action.disabledReason}
            variant={action.destructive ? 'destructive' : undefined}
            opensFloatingUi={action.opensFloatingUi}
            data-attr={`${MENU_DATA_ATTR_PREFIX}-${action.key}`}
        >
            {action.icon}
            {action.label}
        </SceneMenuBarItem>
    )
}

export function MetricSceneMenuBar({ actions }: { actions: MetricSceneAction[] }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    const inMenu = (menu: MetricSceneMenu): MetricSceneAction[] => actions.filter((action) => action.menu === menu)
    const fileActions = inMenu('file').filter((action) => !action.destructive)
    const destructiveActions = inMenu('file').filter((action) => action.destructive)
    const viewActions = inMenu('view')

    return (
        <SceneMenuBar>
            <SceneMenuBarMenu label="File" dataAttr={`${MENU_DATA_ATTR_PREFIX}-file`}>
                {fileActions.map((action) => (
                    <MetricMenuItem key={action.key} action={action} />
                ))}
                <SceneMenuBarSeparator />
                {destructiveActions.map((action) => (
                    <MetricMenuItem key={action.key} action={action} />
                ))}
            </SceneMenuBarMenu>
            <SceneMenuBarMenu label="Edit" dataAttr={`${MENU_DATA_ATTR_PREFIX}-edit`}>
                {inMenu('edit').map((action) => (
                    <MetricMenuItem key={action.key} action={action} />
                ))}
            </SceneMenuBarMenu>
            {viewActions.length > 0 && (
                <SceneMenuBarMenu label="View" dataAttr={`${MENU_DATA_ATTR_PREFIX}-view`}>
                    {viewActions.map((action) => (
                        <MetricMenuItem key={action.key} action={action} />
                    ))}
                </SceneMenuBarMenu>
            )}
        </SceneMenuBar>
    )
}
