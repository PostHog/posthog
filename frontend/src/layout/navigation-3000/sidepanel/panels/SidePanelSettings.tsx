import { useActions, useValues } from 'kea'
import { sidePanelSettingsLogic } from './sidePanelSettingsLogic'
import { SettingsWithSections } from 'scenes/settings/SettingsRenderer'
import { LemonButton } from '@posthog/lemon-ui'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'
import { SettingsLogicProps, settingsLogic } from 'scenes/settings/settingsLogic'
import { useEffect } from 'react'

export const SidePanelSettings = (): JSX.Element => {
    const { settings } = useValues(sidePanelSettingsLogic)
    const { closeSidePanel, setSettings } = useActions(sidePanelSettingsLogic)

    const settingsLogicProps: SettingsLogicProps = {
        ...settings,
        logicKey: 'sidepanel',
    }
    const { selectedSectionId, selectedLevel } = useValues(settingsLogic(settingsLogicProps))

    useEffect(() => {
        setSettings({
            sectionId: selectedSectionId ?? undefined,
            settingLevelId: selectedLevel,
        })
    }, [selectedSectionId, selectedLevel])

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
                <SettingsWithSections {...settingsLogicProps} />
            </div>
        </div>
    )
}
