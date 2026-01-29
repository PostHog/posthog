import { Tabs } from '@base-ui/react/tabs'
import { useActions, useValues } from 'kea'

import { IconSparkles, IconX } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'

import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'
import { SidePanelTab } from '~/types'

import { SIDE_PANEL_TABS } from './SidePanel'
import { sidePanelLogic } from './sidePanelLogic'
import { sidePanelStateLogic } from './sidePanelStateLogic'

interface SidePanelNavigationProps {
    activeTab: SidePanelTab
    onTabChange: (tab: SidePanelTab) => void
    children: React.ReactNode
}

export function SidePanelNavigation({ activeTab, onTabChange, children }: SidePanelNavigationProps): JSX.Element {
    const { openSidePanel, closeSidePanel } = useActions(sidePanelStateLogic)
    const { scenePanelIsPresent } = useValues(sceneLayoutLogic)
    const { visibleTabs } = useValues(sidePanelLogic)

    return (
        <Tabs.Root
            className={cn(
                'scene-panel-container bg-surface-secondary flex flex-col overflow-hidden h-full min-w-0',
                'z-[var(--z-scene-panel)] lg:rounded-none '
            )}
            value={activeTab}
            onValueChange={(value) => onTabChange(value as SidePanelTab)}
        >
            {/* Header with close button */}
            <div className="h-[50px] flex items-center justify-between gap-2 pl-2 pr-1.5 border-b border-primary shrink-0">
                {/* Tab buttons */}
                <Tabs.List className="relative z-0 flex gap-1 grow">
                    {[
                        ...(scenePanelIsPresent ? [SidePanelTab.Info] : []),
                        SidePanelTab.Discussion,
                        SidePanelTab.AccessControl,
                        SidePanelTab.Notebooks,
                        ...(activeTab === SidePanelTab.Max ? [SidePanelTab.Max] : []),
                    ]
                        .filter((tab) => tab === SidePanelTab.Info || visibleTabs.includes(tab))
                        .map((tab) => {
                            const { Icon, label } = SIDE_PANEL_TABS[tab]!
                            return (
                                <Tabs.Tab
                                    key={tab}
                                    value={tab}
                                    render={(props) => (
                                        <ButtonPrimitive
                                            {...props}
                                            onClick={() => openSidePanel(tab as SidePanelTab)}
                                            tooltip={label}
                                            className="size-[33px] @[600px]/side-panel:w-auto hover:bg-transparent group justify-center @[600px]/side-panel:justify-normal"
                                        >
                                            {tab === SidePanelTab.Max ? (
                                                <IconSparkles
                                                    className={cn(
                                                        'size-4 text-tertiary group-hover:text-primary -mt-[1px] ml-[2px]',
                                                        activeTab === tab ? 'text-primary' : 'text-tertiary'
                                                    )}
                                                />
                                            ) : (
                                                <Icon
                                                    className={cn(
                                                        'size-4 text-tertiary group-hover:text-primary',
                                                        activeTab === tab ? 'text-primary' : 'text-tertiary'
                                                    )}
                                                />
                                            )}
                                            <span
                                                className={cn(
                                                    'hidden @[600px]/side-panel:block text-tertiary group-hover:text-primary',
                                                    activeTab === tab ? 'text-primary' : 'text-tertiary'
                                                )}
                                            >
                                                {label}
                                            </span>
                                        </ButtonPrimitive>
                                    )}
                                />
                            )
                        })}
                    <Tabs.Indicator className="transform-gpu absolute top-1/2 left-0 z-[-1] h-[33px] w-[var(--active-tab-width)] translate-x-[var(--active-tab-left)] -translate-y-1/2 rounded bg-[var(--color-bg-fill-button-tertiary-active)] transition-all duration-200 ease-in-out" />

                    <ButtonPrimitive
                        onClick={() => {
                            closeSidePanel()
                        }}
                        tooltip="Close side panel"
                        tooltipPlacement="bottom-end"
                        iconOnly
                        className="group size-[33px] ml-auto"
                    >
                        <IconX className="text-tertiary size-3 group-hover:text-primary z-10" />
                    </ButtonPrimitive>
                </Tabs.List>
            </div>

            {/* Content area */}
            <Tabs.Panel
                className="h-full grow flex flex-col gap-2 relative -outline-offset-1 outline-blue-800 focus-visible:rounded-md overflow-hidden"
                value={activeTab}
            >
                {children}
            </Tabs.Panel>
        </Tabs.Root>
    )
}
