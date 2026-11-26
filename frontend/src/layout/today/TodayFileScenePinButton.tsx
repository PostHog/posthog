import { useMountedLogic, useValues } from 'kea'

import { sceneFileLogic } from 'lib/components/Scenes/sceneFileLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'

import { fileSystemPinTarget } from './sidebar/fileSystemPinTarget'
import { SidebarPinButton } from './sidebar/SidebarPinButton'
import { isTodayPaneEnabled } from './todayPaneFlags'
import type { TodayRailPane } from './todayShellLogic'

export function TodayFileScenePinButton({
    pane,
    dataAttrKey,
}: {
    pane: TodayRailPane
    dataAttrKey: string
}): JSX.Element | null {
    useMountedLogic(sceneFileLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { projectTreeRefEntry } = useValues(projectTreeDataLogic)
    const target = fileSystemPinTarget(projectTreeRefEntry)
    // While the pane is off, no sidebar would list the pin.
    if (!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV] || !isTodayPaneEnabled(pane, featureFlags) || !target) {
        return null
    }
    return <SidebarPinButton target={target} size="icon-sm" dataAttr={`${dataAttrKey}-title-pin`} />
}
