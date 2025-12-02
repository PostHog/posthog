import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconArrowLeft, IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils'
import { Settings } from 'scenes/settings/Settings'
import { settingsLogic } from 'scenes/settings/settingsLogic'
import { SettingsLogicProps } from 'scenes/settings/types'
import { urls } from 'scenes/urls'

import { SidePanelTab } from '~/types'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { sidePanelStateLogic } from '../sidePanelStateLogic'
import { sidePanelSettingsLogic } from './sidePanelSettingsLogic'

export const SidePanelSettings = (): JSX.Element => {
    const { settings, previousTab } = useValues(sidePanelSettingsLogic)
    const { setSettings, setPreviousTab } = useActions(sidePanelSettingsLogic)
    const { openSidePanel, closeSidePanel } = useActions(sidePanelStateLogic)

    const settingsLogicProps: SettingsLogicProps = {
        ...settings,
        logicKey: `sidepanel:${settings.sectionId}`,
    }
    const { selectedSectionId, selectedLevel } = useValues(settingsLogic(settingsLogicProps))

    useEffect(() => {
        setSettings({
            sectionId: selectedSectionId ?? undefined,
            settingLevelId: selectedLevel,
        })
    }, [selectedSectionId, selectedLevel, setSettings])

    const cameFromMax =
        previousTab === SidePanelTab.Max &&
        (selectedSectionId === 'environment-max' || selectedSectionId === ('project-max' as typeof selectedSectionId))

    return (
        <div className="flex flex-col overflow-hidden">
            <SidePanelPaneHeader
                title={
                    <>
                        {cameFromMax && (
                            <LemonButton
                                size="small"
                                icon={<IconArrowLeft />}
                                onClick={() => {
                                    setPreviousTab(null)
                                    openSidePanel(SidePanelTab.Max)
                                }}
                                tooltip="Back to PostHog AI"
                                tooltipPlacement="bottom-end"
                            />
                        )}
                        {`${capitalizeFirstLetter(selectedLevel)} settings`}
                    </>
                }
            >
                <LemonButton
                    size="small"
                    to={urls.settings(settings.sectionId ?? settings.settingLevelId, settings.settingId)}
                    onClick={() => closeSidePanel()}
                    sideIcon={<IconExternal />}
                >
                    All settings
                </LemonButton>
            </SidePanelPaneHeader>
            <div className="flex-1 p-3 overflow-y-auto">
                <Settings hideSections {...settingsLogicProps} />
            </div>
        </div>
    )
}
