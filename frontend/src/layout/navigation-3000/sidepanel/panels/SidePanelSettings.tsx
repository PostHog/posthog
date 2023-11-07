import { useActions, useValues } from 'kea'
import { sidePanelSettingsLogic } from './sidePanelSettingsLogic'
import { SettingsRenderer } from 'scenes/settings/SettingsRenderer'
import { LemonButton } from '@posthog/lemon-ui'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

export const SidePanelSettings = (): JSX.Element => {
    const { settings } = useValues(sidePanelSettingsLogic)
    const { closeSidePanel } = useActions(sidePanelSettingsLogic)

    // NOTE: Currently we can't detect url changes from the iframe
    return (
        <div className="flex flex-col overflow-hidden">
            <div className="border-b flex-0 p-1 flex items-center justify-end gap-2">
                <LemonButton
                    size="small"
                    to={urls.settings(settings.sectionId ?? settings.settingLevelId, settings.settingId)}
                    onClick={() => closeSidePanel()}
                    icon={<IconOpenInNew />}
                >
                    All settings
                </LemonButton>
                <LemonButton size="small" onClick={() => closeSidePanel()}>
                    Done
                </LemonButton>
            </div>
            <div className="flex-1 p-4 overflow-y-auto">
                <SettingsRenderer {...settings} />
            </div>
        </div>
    )
}
