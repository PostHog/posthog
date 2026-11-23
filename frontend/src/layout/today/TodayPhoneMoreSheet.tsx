import { useActions, useValues } from 'kea'

import { IconEllipsis, IconExternal, IconPencil, IconWarning } from '@posthog/icons'
import { ItemContent, ItemDescription, ItemMenuItem, ItemSeparator, ItemTitle, cn } from '@posthog/quill'

import { helpMenuLogic } from 'lib/components/HelpMenu/helpMenuLogic'
import { posthogStatusLogic } from 'lib/components/HelpMenu/posthogStatusLogic'
import { navSwitchLogic } from 'lib/components/NavSwitch/navSwitchLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { SidePanelTab } from '~/types'

import { todayContextPanelLogic } from './todayContextPanelLogic'
import { TodayPhoneTabsEditor } from './TodayPhoneTabsEditor'
import { todayPhoneTabsLogic } from './todayPhoneTabsLogic'
import { TODAY_PANES } from './todayRailItems'
import { SEVERITY_TEXT_CLASS } from './todayRailSeverity'
import { todayRailStatusLogic } from './todayRailStatusLogic'
import { TodaySheetMenu } from './TodaySheetMenu'
import { TodaySheetSub } from './TodaySheetSub'
import { railPaneHref, todayShellLogic } from './todayShellLogic'
import { TodaySupportTicketsSummary } from './TodaySupportTicketsSummary'
import { TodayTabBarTab } from './TodayTabBarTab'

const ROW_CLASS = 'text-base text-foreground no-underline'

export function TodayPhoneMoreSheet(): JSX.Element {
    const { isHelpMenuOpen } = useValues(helpMenuLogic)
    const { setHelpMenuOpen } = useActions(helpMenuLogic)
    const { statusPageUrl } = useValues(posthogStatusLogic)
    const { statusSeverity, statusText, healthSeverity, healthText, helpSeverity, helpLabel } =
        useValues(todayRailStatusLogic)
    const { switchAvailable, switchLabel } = useValues(navSwitchLogic)
    const { switchNav } = useActions(navSwitchLogic)
    const { activePane, effectivePhaiView, featureFlags } = useValues(todayShellLogic)
    const { phoneMorePanes } = useValues(todayPhoneTabsLogic)
    const { clickRailPane } = useActions(todayShellLogic)
    const { activeTab, docked, floatingOpen } = useValues(todayContextPanelLogic)
    const { togglePanelTab } = useActions(todayContextPanelLogic)
    const close = (): void => setHelpMenuOpen(false)
    const supportOpen = (docked || floatingOpen) && activeTab === SidePanelTab.Support

    return (
        <>
            <TodayTabBarTab
                label="More"
                icon={
                    statusSeverity === 'ok' ? (
                        <IconEllipsis />
                    ) : (
                        <IconWarning className={SEVERITY_TEXT_CLASS[statusSeverity]} />
                    )
                }
                active={isHelpMenuOpen || phoneMorePanes.includes(activePane)}
                dataAttr="help-menu-button"
                severity={helpSeverity}
                aria-label={helpLabel('More')}
                aria-haspopup="dialog"
                onClick={() => setHelpMenuOpen(true)}
            />
            <TodaySheetMenu open={isHelpMenuOpen} onOpenChange={setHelpMenuOpen} title="More">
                {phoneMorePanes.map((pane) => {
                    const href = railPaneHref(pane, effectivePhaiView, featureFlags)
                    return (
                        <ItemMenuItem
                            key={pane}
                            className={cn(ROW_CLASS, '[&_svg]:size-4')}
                            render={href ? <LinkPrimitive to={href} /> : undefined}
                            onClick={(event) => {
                                event.preventDefault()
                                close()
                                clickRailPane(pane)
                            }}
                            aria-current={activePane === pane ? 'page' : undefined}
                            data-attr={`today-rail-${pane}`}
                        >
                            {TODAY_PANES[pane].icon}
                            {TODAY_PANES[pane].label}
                        </ItemMenuItem>
                    )
                })}
                <TodaySheetSub
                    label={
                        <span className="flex items-center gap-2 text-base [&_svg]:size-4">
                            <IconPencil />
                            Edit tabs
                        </span>
                    }
                    title="Edit tabs"
                    dataAttr="today-phone-tabs-edit"
                >
                    <TodayPhoneTabsEditor />
                </TodaySheetSub>
                <ItemSeparator className="my-1" />
                <ItemMenuItem
                    className={ROW_CLASS}
                    onClick={() => {
                        close()
                        if (!supportOpen) {
                            togglePanelTab(SidePanelTab.Support)
                        }
                    }}
                    data-attr="more-menu-support-button"
                >
                    <ItemContent>
                        <ItemTitle>Support</ItemTitle>
                        <ItemDescription>
                            <TodaySupportTicketsSummary />
                        </ItemDescription>
                    </ItemContent>
                </ItemMenuItem>
                <ItemMenuItem
                    className={ROW_CLASS}
                    render={<LinkPrimitive to={statusPageUrl} target="_blank" />}
                    onClick={close}
                    data-attr="more-menu-status-button"
                >
                    <ItemContent>
                        <ItemTitle>Status page</ItemTitle>
                        {statusText && (
                            <ItemDescription className={SEVERITY_TEXT_CLASS[statusSeverity]}>
                                {statusText}
                            </ItemDescription>
                        )}
                    </ItemContent>
                    <IconExternal className="ms-auto size-4 text-muted-foreground" />
                </ItemMenuItem>
                <ItemMenuItem
                    className={ROW_CLASS}
                    render={<LinkPrimitive to={urls.health()} />}
                    onClick={close}
                    data-attr="more-menu-health-button"
                >
                    <ItemContent>
                        <ItemTitle>Health</ItemTitle>
                        {healthText && (
                            <ItemDescription
                                className={SEVERITY_TEXT_CLASS[healthSeverity === 'ok' ? 'none' : healthSeverity]}
                            >
                                {healthText}
                            </ItemDescription>
                        )}
                    </ItemContent>
                </ItemMenuItem>
                {switchAvailable && (
                    <ItemMenuItem
                        className={ROW_CLASS}
                        onClick={() => {
                            close()
                            switchNav('today_more_menu')
                        }}
                        data-attr="more-menu-nav-switch-button"
                    >
                        {switchLabel}
                    </ItemMenuItem>
                )}
                <ItemSeparator className="my-1" />
                <ItemMenuItem
                    className={ROW_CLASS}
                    render={<LinkPrimitive to="https://posthog.com/changelog" target="_blank" />}
                    onClick={close}
                    data-attr="more-menu-changelog-button"
                >
                    Changelog
                    <IconExternal className="ms-auto size-4 text-muted-foreground" />
                </ItemMenuItem>
                <ItemMenuItem
                    className={ROW_CLASS}
                    render={<LinkPrimitive to={urls.exports()} />}
                    onClick={close}
                    data-attr="more-menu-exports-button"
                >
                    Exports
                </ItemMenuItem>
            </TodaySheetMenu>
        </>
    )
}
