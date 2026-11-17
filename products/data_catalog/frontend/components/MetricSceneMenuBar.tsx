import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import type { MetricSceneAction } from '../metricSceneActions'

const RESOURCE_TYPE = 'data-catalog-metric'

export function MetricSceneMenuBar({ actions }: { actions: MetricSceneAction[] }): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    const sceneActions: SceneAction[] = [
        ...actions.filter((action) => !action.destructive),
        ...actions.filter((action) => action.destructive),
    ].map((action) => ({
        group: action.menu,
        section: action.destructive ? 'delete' : 'actions',
        id: `${RESOURCE_TYPE}-menubar-${action.key}`,
        label: action.label,
        icon: action.icon,
        disabledReason: action.disabledReason,
        destructive: action.destructive,
        opensFloatingUi: action.opensFloatingUi,
        onSelect: action.onClick,
    }))

    return <SceneActions actions={sceneActions} dataAttrKey={RESOURCE_TYPE} />
}
