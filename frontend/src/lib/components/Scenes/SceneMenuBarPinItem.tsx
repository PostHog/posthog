import { useActions, useMountedLogic, useValues } from 'kea'

import { IconPin, IconPinFilled } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { scenePinTarget } from 'scenes/analytics/analyticsPinnedLogic'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { SceneMenuBarItem } from '~/layout/scenes/components/SceneMenuBar'
import { pinTargetKey, sidebarPinsLogic } from '~/layout/today/sidebar/sidebarPinsLogic'

import { sceneFileLogic } from './sceneFileLogic'

/** The Today layout drops the File menu's project tree items, so the pin for an analytics item lives in Edit. */
export function SceneMenuBarPinItem({ dataAttrKey }: { dataAttrKey: string }): JSX.Element | null {
    useMountedLogic(sceneFileLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { projectTreeRefEntry } = useValues(projectTreeDataLogic)
    const { pinnedShortcutIds, shortcutDataLoading } = useValues(sidebarPinsLogic)
    const { togglePinned } = useActions(sidebarPinsLogic)
    const target = scenePinTarget(projectTreeRefEntry)
    if (!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV] || !target) {
        return null
    }
    const pinned = pinnedShortcutIds.has(pinTargetKey(target))
    return (
        <SceneMenuBarItem
            disabled={shortcutDataLoading}
            onClick={() => togglePinned(target)}
            data-attr={pinned ? `${dataAttrKey}-menubar-unpin` : `${dataAttrKey}-menubar-pin`}
        >
            {pinned ? <IconPinFilled /> : <IconPin />}
            {pinned ? 'Unpin from sidebar' : 'Pin to sidebar'}
        </SceneMenuBarItem>
    )
}
