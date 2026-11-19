import { useActions, useValues } from 'kea'

import { IconEllipsis, IconExternal, IconWarning } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { helpMenuLogic } from 'lib/components/HelpMenu/helpMenuLogic'
import { posthogStatusLogic } from 'lib/components/HelpMenu/posthogStatusLogic'
import { navSwitchLogic } from 'lib/components/NavSwitch/navSwitchLogic'
import { urls } from 'scenes/urls'

import { todayMenuLinkItem } from './todayMenuLinkItem'
import { TodayMoreMenuSupportItem } from './TodayMoreMenuSupportItem'
import { TodayNavSwitchMenuItem } from './TodayNavSwitchMenuItem'
import { TODAY_PANES } from './todayRailItems'
import { SEVERITY_TEXT_CLASS } from './todayRailSeverity'
import { todayRailStatusLogic } from './todayRailStatusLogic'
import { TodayRailTile } from './TodayRailTile'
import { TodayRailPane, railPaneHref, todayShellLogic } from './todayShellLogic'
import { TodayTabBarTab } from './TodayTabBarTab'
import { clickPoint } from './todayTourGeometry'
import { todayTourLogic } from './todayTourLogic'

/**
 * The "More" menu, on the rail or in the phone layout's tab bar. The help menu shortcut opens it too.
 * Its `data-attr`s are pinned: they match the classic help menu, so autocapture data stays continuous.
 */
export function TodayMoreMenu({
    placement = 'rail',
    overflowPanes = [],
}: {
    placement?: 'rail' | 'tab-bar'
    overflowPanes?: TodayRailPane[]
}): JSX.Element {
    const { isHelpMenuOpen } = useValues(helpMenuLogic)
    const { setHelpMenuOpen } = useActions(helpMenuLogic)
    const { statusPageUrl } = useValues(posthogStatusLogic)
    const { statusSeverity, statusText, healthSeverity, healthText, moreSeverity, moreLabel } =
        useValues(todayRailStatusLogic)
    const { switchAvailable, switchFlagOn } = useValues(navSwitchLogic)
    const { tourActive } = useValues(todayTourLogic)
    const { startTour } = useActions(todayTourLogic)
    const { activePane, effectivePhaiView, featureFlags } = useValues(todayShellLogic)
    const { clickRailPane } = useActions(todayShellLogic)
    const overflowActive = overflowPanes.includes(activePane)
    const Tile = placement === 'tab-bar' ? TodayTabBarTab : TodayRailTile

    return (
        // The tour opens this menu and shows its card beside it. A modal menu would swallow the first click on the card.
        <DropdownMenu open={isHelpMenuOpen} onOpenChange={setHelpMenuOpen} modal={!tourActive}>
            <DropdownMenuTrigger
                render={
                    <Tile
                        label="More"
                        icon={
                            statusSeverity === 'ok' ? (
                                <IconEllipsis />
                            ) : (
                                <IconWarning className={SEVERITY_TEXT_CLASS[statusSeverity]} />
                            )
                        }
                        active={isHelpMenuOpen || overflowActive}
                        dataAttr="help-menu-button"
                        severity={moreSeverity}
                        aria-label={moreLabel}
                    />
                }
            />
            <DropdownMenuContent side={placement === 'tab-bar' ? 'top' : 'right'} align="end" className="w-56">
                {overflowPanes.length > 0 && (
                    <>
                        {overflowPanes.map((pane) => {
                            const href = railPaneHref(pane, effectivePhaiView, featureFlags)
                            return (
                                <DropdownMenuItem
                                    key={pane}
                                    render={href ? todayMenuLinkItem(href) : <Button size="row" left />}
                                    onClick={(event) => {
                                        event.preventDefault()
                                        clickRailPane(pane)
                                    }}
                                    aria-current={activePane === pane ? 'page' : undefined}
                                    data-attr={`today-rail-${pane}`}
                                >
                                    {TODAY_PANES[pane].icon}
                                    {TODAY_PANES[pane].label}
                                </DropdownMenuItem>
                            )
                        })}
                        <DropdownMenuSeparator />
                    </>
                )}
                <TodayMoreMenuSupportItem />
                <DropdownMenuSeparator />
                <DropdownMenuItem
                    render={todayMenuLinkItem(statusPageUrl, { external: true })}
                    description={
                        statusText && <span className={SEVERITY_TEXT_CLASS[statusSeverity]}>{statusText}</span>
                    }
                    data-attr="more-menu-status-button"
                >
                    Status page
                    <IconExternal data-icon="inline-end" className="ms-auto" />
                </DropdownMenuItem>
                <DropdownMenuItem
                    render={todayMenuLinkItem(urls.health())}
                    description={
                        healthText && (
                            <span className={SEVERITY_TEXT_CLASS[healthSeverity === 'ok' ? 'none' : healthSeverity]}>
                                {healthText}
                            </span>
                        )
                    }
                    data-attr="more-menu-health-button"
                >
                    Health
                </DropdownMenuItem>
                {/* Also reaches people enrolled without the switch, who never see the dialog that offers the tour. */}
                {switchFlagOn && !tourActive && (
                    <DropdownMenuItem
                        // The tour's cursor starts where this click happened.
                        onClick={(event) => startTour(clickPoint(event))}
                        data-attr="more-menu-take-tour-button"
                    >
                        Take the tour
                    </DropdownMenuItem>
                )}
                {switchAvailable && <TodayNavSwitchMenuItem />}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                    render={todayMenuLinkItem('https://posthog.com/changelog', { external: true })}
                    data-attr="more-menu-changelog-button"
                >
                    Changelog
                    <IconExternal data-icon="inline-end" className="ms-auto" />
                </DropdownMenuItem>
                <DropdownMenuItem render={todayMenuLinkItem(urls.exports())} data-attr="more-menu-exports-button">
                    Exports
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
