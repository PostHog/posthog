import { useActions, useValues } from 'kea'
import { ComponentPropsWithoutRef, forwardRef } from 'react'

import { IconSearch } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { NewAccountMenu } from 'lib/components/Account/NewAccountMenu'
import { pendingInvitesLogic } from 'lib/components/Account/pendingInvitesLogic'
import { PendingInviteDot } from 'lib/components/Account/ProjectMenu'
import { commandLogic } from 'lib/components/Command/commandLogic'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { organizationLogic } from 'scenes/organizationLogic'

import { TODAY_PANES, TODAY_RAIL_PANES } from './todayRailItems'
import { TodayRailTile } from './TodayRailTile'
import { TODAY_RAIL_WIDTH, railPaneHref, todayShellLogic } from './todayShellLogic'

const RailUtility = forwardRef<
    HTMLButtonElement,
    { label: string; children: JSX.Element } & ComponentPropsWithoutRef<typeof Button>
>(function RailUtility({ label, children, ...props }, ref): JSX.Element {
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
            <TooltipContent side="right">{label}</TooltipContent>
        </Tooltip>
    )
})

export function TodayRail(): JSX.Element {
    const { activePane, sidebarVisible } = useValues(todayShellLogic)
    const { clickRailPane } = useActions(todayShellLogic)
    const { toggleCommand } = useActions(commandLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { pendingInvites } = useValues(pendingInvitesLogic)

    return (
        <nav
            aria-label="Main"
            className="flex shrink-0 flex-col items-center gap-3 pt-2.5 pb-3"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: TODAY_RAIL_WIDTH }}
        >
            {TODAY_RAIL_PANES.map((pane) => (
                <TodayRailTile
                    key={pane}
                    label={TODAY_PANES[pane].label}
                    icon={TODAY_PANES[pane].icon}
                    active={activePane === pane}
                    to={railPaneHref(pane)}
                    onClick={() => clickRailPane(pane)}
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
            </div>
        </nav>
    )
}
