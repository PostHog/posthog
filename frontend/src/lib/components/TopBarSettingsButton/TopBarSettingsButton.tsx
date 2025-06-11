import { IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'

import { topBarSettingsButtonLogic } from './topBarSettingsButtonLogic'

export function TopBarSettingsButton(): JSX.Element | null {
    const { loadedSceneSettingsSectionId } = useValues(topBarSettingsButtonLogic)
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)

    if (!loadedSceneSettingsSectionId) {
        return null
    }

    return (
        <span className="relative inline-flex">
            <LemonButton
                size="small"
                icon={<IconGear />}
                onClick={() => openSettingsPanel({ sectionId: loadedSceneSettingsSectionId })}
                tooltip="See settings"
            />
        </span>
    )
}
