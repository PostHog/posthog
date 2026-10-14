import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { TodayAccountMenu } from './TodayAccountMenu'
import { TodayOrgMenu } from './TodayOrgMenu'
import { TODAY_PANES, TODAY_RAIL_PANES } from './todayRailItems'
import { TodayRailTile } from './TodayRailTile'
import { TODAY_RAIL_WIDTH, railPaneHref, todayShellLogic } from './todayShellLogic'

export function TodayRail(): JSX.Element {
    const { activePane } = useValues(todayShellLogic)
    const { clickRailPane } = useActions(todayShellLogic)

    return (
        <nav
            aria-label="Main"
            className="TodayShell__rail flex shrink-0 flex-col items-center gap-3 bg-[var(--chrome)] pt-1.5 pb-3"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: TODAY_RAIL_WIDTH }}
        >
            <TodayOrgMenu />
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
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={
                        <Button
                            size="icon"
                            aria-label="Settings"
                            nativeButton={false}
                            render={<LinkPrimitive to={urls.settings('project')} />}
                            className="mt-auto size-10 rounded-md text-muted-foreground hover:text-foreground [&_svg]:size-5"
                            // pinned: autocapture data-attr
                            data-attr="today-settings"
                        />
                    }
                >
                    <IconGear />
                </TooltipTrigger>
                <TooltipContent side="right">Settings</TooltipContent>
            </Tooltip>
            <TodayAccountMenu />
        </nav>
    )
}
