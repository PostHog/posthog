import { useActions, useValues } from 'kea'

import { DropdownMenuItem, DropdownMenuSeparator, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { helpMenuLogic } from 'lib/components/HelpMenu/helpMenuLogic'
import { OLD_NAV_SUNSET, navSwitchLogic } from 'lib/components/NavSwitch/navSwitchLogic'
import { useSwitchHintFocus } from 'lib/components/NavSwitch/useSwitchHintFocus'
import { getAppContext } from 'lib/utils/getAppContext'

import { todayTourLogic } from './todayTourLogic'

/**
 * The new navigation's "More" menu entry for the old one. It is what `NavSwitchMoreMenuItem` is in the old navigation.
 * Its `data-attr` is pinned: it matches the classic help menu, so autocapture data stays continuous.
 */
export function TodayNavSwitchMenuItem(): JSX.Element {
    const { switchLabel, switchHintVisible } = useValues(navSwitchLogic)
    const { switchNav, hideSwitchHint } = useActions(navSwitchLogic)
    const { setHelpMenuOpen } = useActions(helpMenuLogic)
    const { resetDesignTour } = useActions(todayTourLogic)
    const itemRef = useSwitchHintFocus<HTMLDivElement>()

    return (
        <>
            <DropdownMenuSeparator />
            {/* Shown only while the hint points here, after someone dismisses the "PostHog is changing" dialog. */}
            <Tooltip
                open={switchHintVisible}
                onOpenChange={(open, { reason }) => {
                    if (!open) {
                        hideSwitchHint()
                        // The tooltip takes the first Escape, which would leave the menu open behind it.
                        if (reason === 'escape-key') {
                            setHelpMenuOpen(false)
                        }
                    }
                }}
            >
                <TooltipTrigger
                    render={
                        <DropdownMenuItem
                            ref={itemRef}
                            description={`Available until ${OLD_NAV_SUNSET}. You can switch back to the new navigation any time.`}
                            onClick={() => switchNav('today_more_menu')}
                            data-attr="more-menu-nav-switch-button"
                        >
                            {switchLabel}
                        </DropdownMenuItem>
                    }
                />
                <TooltipContent side="right">You can switch back here any time.</TooltipContent>
            </Tooltip>
            {getAppContext()?.preflight?.is_debug && (
                <DropdownMenuItem
                    description="Local development only. Clears the saved tour and card state, then reloads the page."
                    onClick={resetDesignTour}
                    data-attr="more-menu-reset-design-tour"
                >
                    Reset design tour
                </DropdownMenuItem>
            )}
        </>
    )
}
