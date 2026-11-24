import { useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { DropdownMenuItem, DropdownMenuSeparator } from '@posthog/quill'

import { posthogStatusLogic } from 'lib/components/HelpMenu/posthogStatusLogic'
import { navSwitchLogic } from 'lib/components/NavSwitch/navSwitchLogic'
import { urls } from 'scenes/urls'

import { TodayHelpSupportItem } from './TodayHelpSupportItem'
import { todayMenuLinkItem } from './todayMenuLinkItem'
import { TodayNavSwitchMenuItem } from './TodayNavSwitchMenuItem'
import { SEVERITY_TEXT_CLASS } from './todayRailSeverity'
import { todayRailStatusLogic } from './todayRailStatusLogic'

// pinned: the items' `data-attr`s match the classic help menu, so autocapture data stays continuous.
export function TodayHelpMenuItems(): JSX.Element {
    const { statusPageUrl } = useValues(posthogStatusLogic)
    const { statusSeverity, statusText, healthSeverity, healthText } = useValues(todayRailStatusLogic)
    const { switchAvailable } = useValues(navSwitchLogic)

    return (
        <>
            <TodayHelpSupportItem />
            <DropdownMenuSeparator />
            <DropdownMenuItem
                render={todayMenuLinkItem(statusPageUrl, { external: true })}
                description={statusText && <span className={SEVERITY_TEXT_CLASS[statusSeverity]}>{statusText}</span>}
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
        </>
    )
}
