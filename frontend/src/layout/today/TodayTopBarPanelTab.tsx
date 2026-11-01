import { useActions, useValues } from 'kea'
import { ComponentType, useState } from 'react'

import { IconPulse, IconSparkles } from '@posthog/icons'
import { Button, Kbd, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { SIDE_PANEL_TABS } from '~/layout/navigation-3000/sidepanel/sidePanelTabs'
import { SidePanelTab } from '~/types'

import { todayContextPanelLogic } from './todayContextPanelLogic'

// The top bar's own icons where the side panel's would read wrong at this size.
const TODAY_TAB_ICONS: Partial<Record<SidePanelTab, ComponentType>> = {
    [SidePanelTab.Max]: IconSparkles,
    [SidePanelTab.Activity]: IconPulse,
}

export function TodayTopBarPanelTab({ tab }: { tab: SidePanelTab }): JSX.Element {
    const { activeTab, docked, floatingOpen, launcherHintVisible } = useValues(todayContextPanelLogic)
    const { togglePanelTab, hideLauncherHint } = useActions(todayContextPanelLogic)
    // Controlled, so PostHog AI's tooltip can also point here after the user dismisses the floating button.
    const [hovered, setHovered] = useState(false)
    const launcherHint = tab === SidePanelTab.Max && launcherHintVisible

    const { label: tabLabel } = SIDE_PANEL_TABS[tab]
    const Icon = TODAY_TAB_ICONS[tab] ?? SIDE_PANEL_TABS[tab].Icon
    const pressed = (docked || floatingOpen) && activeTab === tab
    const label = pressed ? `Close ${tabLabel}` : tabLabel

    return (
        <Tooltip
            disableHoverablePopup
            open={launcherHint || hovered}
            onOpenChange={(open) => {
                setHovered(open)
                if (!open && launcherHint) {
                    hideLauncherHint()
                }
            }}
        >
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size="icon"
                        aria-label={label}
                        aria-pressed={pressed}
                        className="text-muted-foreground hover:text-foreground aria-pressed:bg-[var(--fill-selected)] aria-pressed:text-foreground"
                        onClick={() => togglePanelTab(tab)}
                        // pinned: the PostHog AI button keeps the side panel button's data-attr
                        data-attr={
                            tab === SidePanelTab.Max ? 'today-top-bar-side-panel' : `today-top-bar-panel-tab-${tab}`
                        }
                    />
                }
            >
                <Icon />
            </TooltipTrigger>
            <TooltipContent side="bottom" align="end">
                {launcherHint ? (
                    "It's here when you need it"
                ) : (
                    <>
                        {label}
                        {tab === SidePanelTab.Max && <Kbd>]</Kbd>}
                    </>
                )}
            </TooltipContent>
        </Tooltip>
    )
}
