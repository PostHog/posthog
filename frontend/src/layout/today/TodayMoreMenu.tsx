import { useActions, useValues } from 'kea'

import { IconEllipsis, IconExternal, IconWarning } from '@posthog/icons'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { helpMenuLogic } from 'lib/components/HelpMenu/helpMenuLogic'
import { posthogStatusLogic } from 'lib/components/HelpMenu/posthogStatusLogic'
import { urls } from 'scenes/urls'

import { todayMenuLinkItem } from './todayMenuLinkItem'
import { SEVERITY_TEXT_CLASS } from './todayRailSeverity'
import { todayRailStatusLogic } from './todayRailStatusLogic'
import { TodayRailTile } from './TodayRailTile'

/**
 * The rail's "More" menu. The help menu shortcut opens it too.
 * Its `data-attr`s are pinned: they match the classic help menu, so autocapture data stays continuous.
 */
export function TodayMoreMenu(): JSX.Element {
    const { isHelpMenuOpen } = useValues(helpMenuLogic)
    const { setHelpMenuOpen } = useActions(helpMenuLogic)
    const { statusPageUrl } = useValues(posthogStatusLogic)
    const { statusSeverity, statusText, healthText, moreSeverity, moreLabel } = useValues(todayRailStatusLogic)

    return (
        <DropdownMenu open={isHelpMenuOpen} onOpenChange={setHelpMenuOpen}>
            <DropdownMenuTrigger
                render={
                    <TodayRailTile
                        label="More"
                        icon={
                            statusSeverity === 'ok' ? (
                                <IconEllipsis />
                            ) : (
                                <IconWarning className={SEVERITY_TEXT_CLASS[statusSeverity]} />
                            )
                        }
                        active={isHelpMenuOpen}
                        dataAttr="help-menu-button"
                        severity={moreSeverity}
                        aria-label={moreLabel}
                    />
                }
            />
            <DropdownMenuContent side="right" align="end" className="w-56">
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
                    description={healthText}
                    data-attr="more-menu-health-button"
                >
                    Health
                </DropdownMenuItem>
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
