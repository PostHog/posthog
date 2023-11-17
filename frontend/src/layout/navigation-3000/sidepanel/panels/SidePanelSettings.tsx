import { useActions, useValues } from 'kea'
import { sidePanelSettingsLogic } from './sidePanelSettingsLogic'
import { Settings } from 'scenes/settings/Settings'
import { LemonButton } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { SettingsLogicProps, settingsLogic } from 'scenes/settings/settingsLogic'
import { useEffect } from 'react'
import { SidePanelPaneHeader } from '../components/SidePanelPane'
import { IconExternal } from '@posthog/icons'

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

    return (
        <div className="flex flex-col overflow-hidden">
            <SidePanelPaneHeader>
                <LemonButton
                    size="small"
                    to={urls.settings(settings.sectionId ?? settings.settingLevelId, settings.settingId)}
                    onClick={() => closeSidePanel()}
                    sideIcon={<IconExternal />}
                >
                    All settings
                </LemonButton>
            </SidePanelPaneHeader>
            <div className="flex-1 p-4 overflow-y-auto">
                <Settings {...settingsLogicProps} />
            </div>
        </div>
    )
}
