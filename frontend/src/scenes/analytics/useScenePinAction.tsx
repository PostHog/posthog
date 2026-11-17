import { useActions, useMountedLogic, useValues } from 'kea'

import { IconPin, IconPinFilled } from '@posthog/icons'

import { sceneFileLogic } from 'lib/components/Scenes/sceneFileLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { scenePinTarget } from 'scenes/analytics/analyticsPinnedLogic'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import type { SceneAction, SceneActionGroup } from '~/layout/scenes/sceneActions/sceneActionModel'
import { pinTargetKey, sidebarPinsLogic } from '~/layout/today/sidebar/sidebarPinsLogic'

/** Pins an analytics item to the Today sidebar. The Today layout drops the File menu's tree items, so it lives in Edit. */
export function useScenePinAction(
    dataAttrKey: string,
    { group = 'edit', section }: { group?: SceneActionGroup; section?: string } = {}
): SceneAction[] {
    useMountedLogic(sceneFileLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { projectTreeRefEntry } = useValues(projectTreeDataLogic)
    const { pinnedShortcutIds, shortcutDataLoading } = useValues(sidebarPinsLogic)
    const { togglePinned } = useActions(sidebarPinsLogic)
    const target = scenePinTarget(projectTreeRefEntry)
    if (!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV] || !target) {
        return []
    }
    const pinned = pinnedShortcutIds.has(pinTargetKey(target))
    return [
        {
            group,
            section,
            id: pinned ? `${dataAttrKey}-menubar-unpin` : `${dataAttrKey}-menubar-pin`,
            label: pinned ? 'Unpin from sidebar' : 'Pin to sidebar',
            icon: pinned ? <IconPinFilled /> : <IconPin />,
            disabledReason: shortcutDataLoading ? 'Loading pins' : undefined,
            onSelect: () => togglePinned(target),
        },
    ]
}
