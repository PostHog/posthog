import { useActions, useMountedLogic, useValues } from 'kea'

import { IconPin, IconPinFilled } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { analyticsPinnedLogic, pinKey } from 'scenes/analytics/analyticsPinnedLogic'
import { fileSystemBaseType, fileSystemEntryName, isAnalyticsType } from 'scenes/analytics/analyticsUtils'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { SceneMenuBarItem } from '~/layout/scenes/components/SceneMenuBar'

import { sceneFileLogic } from './sceneFileLogic'

/** The Today layout drops the File menu's project tree items, so the pin for an analytics item lives in Edit. */
export function SceneMenuBarPinItem({ dataAttrKey }: { dataAttrKey: string }): JSX.Element | null {
    useMountedLogic(sceneFileLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { projectTreeRefEntry } = useValues(projectTreeDataLogic)
    const { pinnedShortcutIds, shortcutDataLoading } = useValues(analyticsPinnedLogic)
    const { togglePinned } = useActions(analyticsPinnedLogic)
    const type = fileSystemBaseType(projectTreeRefEntry?.type)
    if (!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV] || !projectTreeRefEntry?.ref || !isAnalyticsType(type)) {
        return null
    }
    const ref = projectTreeRefEntry.ref
    const pinned = pinnedShortcutIds.has(pinKey(type, ref))
    return (
        <SceneMenuBarItem
            disabled={shortcutDataLoading}
            onClick={() =>
                togglePinned({
                    type,
                    ref,
                    name: fileSystemEntryName(projectTreeRefEntry),
                    href: projectTreeRefEntry.href,
                })
            }
            data-attr={pinned ? `${dataAttrKey}-menubar-unpin` : `${dataAttrKey}-menubar-pin`}
        >
            {pinned ? <IconPinFilled /> : <IconPin />}
            {pinned ? 'Unpin from sidebar' : 'Pin to sidebar'}
        </SceneMenuBarItem>
    )
}
