import { useActions, useValues } from 'kea'

import {
    IconBook,
    IconChat,
    IconHome,
    IconLogomark,
    IconSearch,
    IconSidebarClose,
    IconSidebarOpen,
    IconWrench,
} from '@posthog/icons'

import { NewAccountMenu } from 'lib/components/Account/NewAccountMenu'
import { commandLogic } from 'lib/components/Command/commandLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { cn } from 'lib/utils/css-classes'

import { TODAY_RAIL_WIDTH, TodayRailPane, todayShellLogic } from './todayShellLogic'

const RAIL_ITEMS: { pane: TodayRailPane; label: string; icon: JSX.Element }[] = [
    { pane: 'home', label: 'Home', icon: <IconHome /> },
    { pane: 'spaces', label: 'Spaces', icon: <IconChat /> },
    { pane: 'library', label: 'Library', icon: <IconBook /> },
    { pane: 'tools', label: 'Tools', icon: <IconWrench /> },
]

export function TodayRail(): JSX.Element {
    const { activePane, sidebarOpen } = useValues(todayShellLogic)
    const { pickPane, toggleSidebar } = useActions(todayShellLogic)
    const { toggleCommand } = useActions(commandLogic)

    return (
        <nav
            aria-label="Main"
            className="flex flex-col items-center gap-1 py-3 shrink-0"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: TODAY_RAIL_WIDTH }}
        >
            <div className="flex items-center justify-center size-9 mb-2 text-primary" aria-hidden>
                <IconLogomark className="size-6" />
            </div>
            {RAIL_ITEMS.map(({ pane, label, icon }) => {
                const active = activePane === pane
                return (
                    <ButtonPrimitive
                        key={pane}
                        iconOnly
                        size="lg"
                        active={active}
                        aria-label={label}
                        aria-current={active ? 'page' : undefined}
                        tooltip={label}
                        tooltipPlacement="right"
                        data-attr={`today-rail-${pane}`}
                        className={cn('text-secondary [&_svg]:size-5', active && 'text-primary')}
                        onClick={() => pickPane(pane)}
                    >
                        {icon}
                    </ButtonPrimitive>
                )
            })}
            <div className="mt-auto flex flex-col items-center gap-1">
                <ButtonPrimitive
                    iconOnly
                    size="lg"
                    aria-label="Search"
                    tooltip="Search"
                    tooltipPlacement="right"
                    data-attr="today-rail-search"
                    className="text-secondary [&_svg]:size-5"
                    onClick={() => toggleCommand('nav-search-button')}
                >
                    <IconSearch />
                </ButtonPrimitive>
                <ButtonPrimitive
                    iconOnly
                    size="lg"
                    aria-label={sidebarOpen ? 'Hide sidebar' : 'Show sidebar'}
                    tooltip={sidebarOpen ? 'Hide sidebar' : 'Show sidebar'}
                    tooltipPlacement="right"
                    data-attr="today-rail-toggle-sidebar"
                    className="text-secondary [&_svg]:size-5"
                    onClick={toggleSidebar}
                >
                    {sidebarOpen ? <IconSidebarClose /> : <IconSidebarOpen />}
                </ButtonPrimitive>
                <NewAccountMenu isLayoutNavCollapsed />
            </div>
        </nav>
    )
}
