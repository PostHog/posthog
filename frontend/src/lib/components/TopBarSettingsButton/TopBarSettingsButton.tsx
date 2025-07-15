import { IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'

import { topBarSettingsButtonLogic } from './topBarSettingsButtonLogic'

export function TopBarSettingsButton(): JSX.Element | null {
    const { loadedSceneSettingsSectionId } = useValues(topBarSettingsButtonLogic)
    const { openSettingsPanel, closeSettingsPanel } = useActions(sidePanelSettingsLogic)
    const { isOpen } = useValues(sidePanelSettingsLogic)

    if (!loadedSceneSettingsSectionId) {
        return null
    }

    return (
        <span className="relative inline-flex">
            <LemonButton
                size="small"
                icon={<IconGear />}
                onClick={() =>
                    isOpen ? closeSettingsPanel() : openSettingsPanel({ sectionId: loadedSceneSettingsSectionId })
                }
                tooltip="Toggle settings"
            />
        </span>
    )
}
