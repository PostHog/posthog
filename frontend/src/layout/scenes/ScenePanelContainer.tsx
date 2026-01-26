import { Tabs } from '@base-ui/react/tabs'
import { useValues } from 'kea'
import { Suspense, useMemo, useState } from 'react'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'
import { sceneLogic } from 'scenes/sceneLogic'
import { ScenePanelTabConfig } from 'scenes/sceneTypes'

import { SceneTitlePanelButton } from './components/SceneTitleSection'
import { sceneLayoutLogic } from './sceneLayoutLogic'

/**
 * Renders the scene panel based on the active scene's scenePanelTabs config.
 * This is a declarative approach - no portals needed.
 */
export function ScenePanelContainer(): JSX.Element | null {
    const { sceneConfig, activeLoadedScene } = useValues(sceneLogic)
    const { scenePanelOpenManual } = useValues(sceneLayoutLogic)
    const [activeTabId, setActiveTabId] = useState<string | null>(null)

    const tabs = useMemo((): ScenePanelTabConfig[] | null => {
        if (!sceneConfig?.scenePanelTabs) {
            return null
        }
        if (typeof sceneConfig.scenePanelTabs === 'function') {
            return sceneConfig.scenePanelTabs(
                activeLoadedScene?.sceneParams ?? { params: {}, searchParams: {}, hashParams: {} }
            )
        }
        return sceneConfig.scenePanelTabs
    }, [sceneConfig, activeLoadedScene?.sceneParams])

    // No tabs configured for this scene
    if (!tabs?.length) {
        return null
    }

    // Ensure activeTabId is valid, default to first tab
    const currentTabId = activeTabId && tabs.some((t) => t.id === activeTabId) ? activeTabId : tabs[0].id
    const activeTab = tabs.find((t) => t.id === currentTabId)
    const ActiveContent = activeTab?.Content

    if (!scenePanelOpenManual) {
        return null
    }

    return (
        <Tabs.Root
            className={cn(
                'scene-panel-container bg-surface-secondary flex flex-col overflow-hidden h-full min-w-0 w-[320px]',
                'z-[var(--z-scene-panel)] border-l border-primary lg:rounded-tr-none'
            )}
            value={currentTabId}
            onValueChange={(value) => setActiveTabId(value)}
        >
            {/* Header with close button */}
            <div className="h-[50px] flex items-center justify-between gap-2 px-2 py-2 border-b border-primary shrink-0">
                {/* Tab buttons */}
                <Tabs.List className="relative z-0 flex gap-1 px-1">
                    {tabs.map((tab) => (
                        <Tabs.Tab
                            key={tab.id}
                            value={tab.id}
                            render={(props) => (
                                <ButtonPrimitive
                                    {...props}
                                    iconOnly
                                    onClick={() => setActiveTabId(tab.id)}
                                    tooltip={tab.label}
                                    className="hover:bg-transparent group"
                                >
                                    <tab.Icon
                                        className={cn(
                                            'size-4 text-tertiary group-hover:text-primary',
                                            currentTabId === tab.id ? 'text-primary' : 'text-tertiary'
                                        )}
                                    />
                                </ButtonPrimitive>
                            )}
                        />
                    ))}
                    <Tabs.Indicator className="absolute top-1/2 left-0 z-[-1] size-[30px] translate-x-[var(--active-tab-left)] -translate-y-1/2 rounded-sm bg-[var(--color-bg-fill-button-tertiary-active)] transition-all duration-200 ease-in-out" />
                </Tabs.List>
                <SceneTitlePanelButton inPanel />
            </div>

            {/* Content area */}
            <ScrollableShadows direction="vertical" className="grow flex-1" innerClassName="px-2 py-2" styledScrollbars>
                <Suspense fallback={<SpinnerOverlay />}>
                    <Tabs.Panel
                        className="flex flex-col gap-2 relative -outline-offset-1 outline-blue-800 focus-visible:rounded-md focus-visible:outline focus-visible:outline-2"
                        value={currentTabId}
                    >
                        {ActiveContent && <ActiveContent />}
                    </Tabs.Panel>
                </Suspense>
            </ScrollableShadows>
        </Tabs.Root>
    )
}
