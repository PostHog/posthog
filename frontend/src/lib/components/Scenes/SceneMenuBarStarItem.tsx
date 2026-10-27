import { useActions, useMountedLogic, useValues } from 'kea'

import { IconStar, IconStarFilled } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { analyticsStarredLogic, starKey } from 'scenes/analytics/analyticsStarredLogic'
import { fileSystemBaseType, fileSystemEntryName, isAnalyticsType } from 'scenes/analytics/analyticsUtils'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { SceneMenuBarItem } from '~/layout/scenes/components/SceneMenuBar'

import { sceneFileLogic } from './sceneFileLogic'

/** The Today layout drops the File menu's project tree items, so the star for an analytics item lives in Edit. */
export function SceneMenuBarStarItem({ dataAttrKey }: { dataAttrKey: string }): JSX.Element | null {
    useMountedLogic(sceneFileLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { projectTreeRefEntry } = useValues(projectTreeDataLogic)
    const { starredShortcutIds, shortcutDataLoading } = useValues(analyticsStarredLogic)
    const { toggleStarred } = useActions(analyticsStarredLogic)
    const type = fileSystemBaseType(projectTreeRefEntry?.type)
    if (!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV] || !projectTreeRefEntry?.ref || !isAnalyticsType(type)) {
        return null
    }
    const ref = projectTreeRefEntry.ref
    const starred = starredShortcutIds.has(starKey(type, ref))
    return (
        <SceneMenuBarItem
            disabled={shortcutDataLoading}
            onClick={() =>
                toggleStarred({
                    type,
                    ref,
                    name: fileSystemEntryName(projectTreeRefEntry),
                    href: projectTreeRefEntry.href,
                })
            }
            data-attr={starred ? `${dataAttrKey}-menubar-remove-from-starred` : `${dataAttrKey}-menubar-add-to-starred`}
        >
            {starred ? <IconStarFilled /> : <IconStar />}
            {starred ? 'Remove from starred' : 'Add to starred'}
        </SceneMenuBarItem>
    )
}
