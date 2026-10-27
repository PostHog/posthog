import { useActions, useValues } from 'kea'
import { ComponentType, useState } from 'react'

import { IconChat, IconPulse, IconSparkles, IconSupport } from '@posthog/icons'
import { Button, Kbd, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { sidePanelDiscussionLogic } from '~/layout/navigation-3000/sidepanel/panels/discussion/sidePanelDiscussionLogic'
import { SIDE_PANEL_TABS } from '~/layout/navigation-3000/sidepanel/sidePanelTabs'
import { SidePanelTab } from '~/types'

import { todayContextPanelLogic } from './todayContextPanelLogic'

// The top bar's own icons where the side panel's would read wrong at this size. Support also stays static because the
// side panel's icon reads the ticket logic for its unread count, and this bar renders on every page without live tickets.
// Discussion's side panel icon draws its count as a Lemon badge, so the bar says the count in the tooltip instead.
const TODAY_TAB_ICONS: Partial<Record<SidePanelTab, ComponentType>> = {
    [SidePanelTab.Max]: IconSparkles,
    [SidePanelTab.Support]: IconSupport,
    [SidePanelTab.Activity]: IconPulse,
    [SidePanelTab.Discussion]: IconChat,
}

export function TodayTopBarPanelTab({ tab }: { tab: SidePanelTab }): JSX.Element {
    const { activeTab, docked, floatingOpen, launcherHintVisible } = useValues(todayContextPanelLogic)
    const { togglePanelTab, hideLauncherHint } = useActions(todayContextPanelLogic)
    const { commentCount } = useValues(sidePanelDiscussionLogic)
    // Controlled, so PostHog AI's tooltip can also point here after the user dismisses the floating button.
    const [hovered, setHovered] = useState(false)
    const launcherHint = tab === SidePanelTab.Max && launcherHintVisible

    const { label: tabLabel } = SIDE_PANEL_TABS[tab]
    const Icon = TODAY_TAB_ICONS[tab] ?? SIDE_PANEL_TABS[tab].Icon
    const pressed = (docked || floatingOpen) && activeTab === tab
    const label = pressed ? `Close ${tabLabel}` : tabLabel
    const comments = tab === SidePanelTab.Discussion ? commentCount : 0
    const countLabel = comments > 0 ? pluralize(comments, 'comment') : null

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
                        aria-label={countLabel ? `${label}, ${countLabel}` : label}
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
                        {countLabel && <span className="opacity-70">{countLabel}</span>}
                        {tab === SidePanelTab.Max && <Kbd>]</Kbd>}
                    </>
                )}
            </TooltipContent>
        </Tooltip>
    )
}
