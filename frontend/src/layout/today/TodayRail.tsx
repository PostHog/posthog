import { useActions, useValues } from 'kea'
import { ComponentPropsWithoutRef, forwardRef } from 'react'

import { IconSearch, IconSidebarClose, IconSidebarOpen } from '@posthog/icons'
import { Button, Kbd, Separator, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { Logomark } from 'lib/brand'
import { NewAccountMenu } from 'lib/components/Account/NewAccountMenu'
import { pendingInvitesLogic } from 'lib/components/Account/pendingInvitesLogic'
import { PendingInviteDot } from 'lib/components/Account/ProjectMenu'
import { commandLogic } from 'lib/components/Command/commandLogic'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { isMac } from 'lib/utils/dom'
import { organizationLogic } from 'scenes/organizationLogic'

import { TODAY_RAIL_ITEMS } from './todayRailItems'
import { TodayRailTile } from './TodayRailTile'
import { TODAY_RAIL_WIDTH, railPaneHref, todayShellLogic } from './todayShellLogic'

const RailUtility = forwardRef<
    HTMLButtonElement,
    { label: string; children: JSX.Element; shortcut?: string } & ComponentPropsWithoutRef<typeof Button>
>(function RailUtility({ label, children, shortcut, ...props }, ref): JSX.Element {
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        variant="default"
                        size="icon"
                        aria-label={label}
                        className="relative size-10 rounded-md text-muted-foreground hover:text-foreground [&_svg]:size-5"
                        {...props}
                        ref={ref}
                    />
                }
            >
                {children}
            </TooltipTrigger>
            <TooltipContent side="right">
                {label}
                {shortcut && <Kbd>{shortcut}</Kbd>}
            </TooltipContent>
        </Tooltip>
    )
})

export function TodayRail(): JSX.Element {
    const { activePane, sidebarVisible } = useValues(todayShellLogic)
    const { pickPane, toggleSidebar } = useActions(todayShellLogic)
    const { toggleCommand } = useActions(commandLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { pendingInvites } = useValues(pendingInvitesLogic)

    return (
        <nav
            aria-label="Main"
            className="flex shrink-0 flex-col items-center gap-3 border-r border-[var(--border)] pb-3"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: TODAY_RAIL_WIDTH }}
        >
            {/* h-12 matches QuillSceneHeader, so the line under the logo meets the pane header's bottom border. */}
            <div className="-mb-1 flex h-12 w-full shrink-0 flex-col items-center" aria-hidden>
                <div className="flex flex-1 items-center">
                    <Logomark className="h-auto w-6" />
                </div>
                <Separator />
            </div>
            {TODAY_RAIL_ITEMS.map(({ pane, label, icon }) => (
                <TodayRailTile
                    key={pane}
                    label={label}
                    icon={icon}
                    active={activePane === pane}
                    to={railPaneHref(pane)}
                    onClick={() => pickPane(pane)}
                    dataAttr={`today-rail-${pane}`}
                />
            ))}
            <div className="mt-auto flex flex-col items-center gap-1">
                {!sidebarVisible && (
                    <NewAccountMenu
                        side="right"
                        align="end"
                        renderTrigger={(props) => (
                            <RailUtility {...props} label="Account menu" data-attr="new-account-menu-button">
                                <>
                                    <UploadedLogo
                                        name={currentOrganization?.name ?? '?'}
                                        entityId={currentOrganization?.id ?? ''}
                                        mediaId={currentOrganization?.logo_media_id ?? ''}
                                        size="small"
                                    />
                                    {pendingInvites.length > 0 && (
                                        <PendingInviteDot className="absolute top-1.5 right-1.5" />
                                    )}
                                </>
                            </RailUtility>
                        )}
                    />
                )}
                <RailUtility
                    label="Search"
                    data-attr="today-rail-search"
                    onClick={() => toggleCommand('nav-search-button')}
                >
                    <IconSearch />
                </RailUtility>
                <RailUtility
                    label={sidebarVisible ? 'Hide sidebar' : 'Show sidebar'}
                    shortcut={isMac() ? '⌘B' : 'Ctrl+B'}
                    data-attr="today-rail-toggle-sidebar"
                    onClick={toggleSidebar}
                >
                    {sidebarVisible ? <IconSidebarClose /> : <IconSidebarOpen />}
                </RailUtility>
            </div>
        </nav>
    )
}
