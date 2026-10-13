import { useActions, useValues } from 'kea'

import { IconSidePanel } from '@posthog/icons'
import { Button, Kbd, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'

export function TodayTopBarSidePanelButton(): JSX.Element {
    const { sidePanelOpen } = useValues(sidePanelStateLogic)
    const { defaultTab } = useValues(sidePanelLogic)
    const { openSidePanel, closeSidePanel } = useActions(sidePanelStateLogic)
    const label = sidePanelOpen ? 'Close context panel' : 'Open context panel'

    return (
        <Tooltip disableHoverablePopup>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size="icon"
                        aria-label={label}
                        aria-pressed={sidePanelOpen}
                        className="text-muted-foreground hover:text-foreground aria-pressed:bg-[var(--fill-selected)] aria-pressed:text-foreground"
                        onClick={() => (sidePanelOpen ? closeSidePanel() : openSidePanel(defaultTab))}
                        data-attr="today-top-bar-side-panel"
                    />
                }
            >
                <IconSidePanel />
            </TooltipTrigger>
            <TooltipContent side="bottom" align="end">
                {label}
                <Kbd>]</Kbd>
            </TooltipContent>
        </Tooltip>
    )
}
