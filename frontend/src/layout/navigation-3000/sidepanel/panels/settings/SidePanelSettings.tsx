import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconArrowLeft, IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useOpenAi } from 'scenes/max/useOpenAi'
import { Settings } from 'scenes/settings/Settings'
import { settingsLogic } from 'scenes/settings/settingsLogic'
import { SettingsLogicProps } from 'scenes/settings/types'
import { urls } from 'scenes/urls'

import { SidePanelTab } from '~/types'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { SidePanelContentContainer } from '../../SidePanelContentContainer'
import { sidePanelStateLogic } from '../../sidePanelStateLogic'
import { sidePanelSettingsLogic } from './sidePanelSettingsLogic'

export const SidePanelSettings = (): JSX.Element => {
    const { effectiveSettings, previousTab } = useValues(sidePanelSettingsLogic)
    const { setSettings, setPreviousTab } = useActions(sidePanelSettingsLogic)
    const { closeSidePanel } = useActions(sidePanelStateLogic)
    const { openAi } = useOpenAi()
    const scrollContainerRef = useRef<HTMLDivElement | null>(null)

    const settingsLogicProps: SettingsLogicProps = {
        ...effectiveSettings,
        logicKey: `sidepanel:${effectiveSettings.sectionId}`,
    }
    const { selectedSectionId, selectedLevel } = useValues(settingsLogic(settingsLogicProps))

    useEffect(() => {
        setSettings({
            sectionId: selectedSectionId ?? undefined,
            settingLevelId: selectedLevel,
        })
    }, [selectedSectionId, selectedLevel, setSettings])

    useEffect(() => {
        if (effectiveSettings.settingId) {
            const timeout = setTimeout(() => {
                const container = scrollContainerRef.current
                if (!container) {
                    return
                }

                container
                    .querySelector<HTMLElement>(`[id="${effectiveSettings.settingId}"]`)
                    ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
            }, 1000 / 60)
            return () => clearTimeout(timeout)
        }
    }, [effectiveSettings.settingId])

    const cameFromMax =
        previousTab === SidePanelTab.Max &&
        (selectedSectionId === 'environment-max' || selectedSectionId === ('project-max' as typeof selectedSectionId))

    return (
        <div className="flex flex-col overflow-hidden flex-1">
            <SidePanelContentContainer>
                <SidePanelPaneHeader
                    title={
                        <>
                            {cameFromMax && (
                                <LemonButton
                                    size="small"
                                    icon={<IconArrowLeft />}
                                    onClick={() => {
                                        setPreviousTab(null)
                                        openAi()
                                    }}
                                    tooltip="Back to PostHog AI"
                                    tooltipPlacement="bottom-end"
                                />
                            )}
                            Settings
                        </>
                    }
                >
                    <LemonButton
                        size="small"
                        to={urls.settings(
                            effectiveSettings.sectionId ?? effectiveSettings.settingLevelId,
                            effectiveSettings.settingId
                        )}
                        onClick={() => closeSidePanel()}
                        sideIcon={<IconExternal />}
                    >
                        All settings
                    </LemonButton>
                </SidePanelPaneHeader>
                <div className="flex-1 p-3 pt-0 overflow-y-auto" ref={scrollContainerRef}>
                    <Settings hideSections {...settingsLogicProps} />
                </div>
            </SidePanelContentContainer>
        </div>
    )
}
