import { useMountedLogic, useValues } from 'kea'

import { sceneFileLogic } from 'lib/components/Scenes/sceneFileLogic'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { SidebarPinButton } from '~/layout/today/sidebar/SidebarPinButton'

import { analyticsPinnedLogic, scenePinTarget } from './analyticsPinnedLogic'

export function AnalyticsScenePinButton({ dataAttrKey }: { dataAttrKey: string }): JSX.Element | null {
    useMountedLogic(sceneFileLogic)
    // Reports the pin once it saves.
    useMountedLogic(analyticsPinnedLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const { projectTreeRefEntry } = useValues(projectTreeDataLogic)
    const target = scenePinTarget(projectTreeRefEntry)
    if (!todayRailNav || !target) {
        return null
    }
    return <SidebarPinButton target={target} size="icon-sm" dataAttr={`${dataAttrKey}-title-pin`} />
}
