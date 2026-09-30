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

import { TodayRailButton } from './TodayRailButton'
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
            className="flex shrink-0 flex-col items-center gap-1 py-3"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ width: TODAY_RAIL_WIDTH }}
        >
            <div className="mb-2 flex size-9 items-center justify-center" aria-hidden>
                <IconLogomark className="size-6" />
            </div>
            {RAIL_ITEMS.map(({ pane, label, icon }) => (
                <TodayRailButton
                    key={pane}
                    label={label}
                    current={activePane === pane}
                    dataAttr={`today-rail-${pane}`}
                    onClick={() => pickPane(pane)}
                >
                    {icon}
                </TodayRailButton>
            ))}
            <div className="mt-auto flex flex-col items-center gap-1">
                <TodayRailButton
                    label="Search"
                    dataAttr="today-rail-search"
                    onClick={() => toggleCommand('nav-search-button')}
                >
                    <IconSearch />
                </TodayRailButton>
                <TodayRailButton
                    label={sidebarOpen ? 'Hide sidebar' : 'Show sidebar'}
                    dataAttr="today-rail-toggle-sidebar"
                    onClick={toggleSidebar}
                >
                    {sidebarOpen ? <IconSidebarClose /> : <IconSidebarOpen />}
                </TodayRailButton>
                {/* The account menu is shared with the flag-off navigation, so it stays on LemonUI. */}
                <div data-not-quill>
                    <NewAccountMenu isLayoutNavCollapsed />
                </div>
            </div>
        </nav>
    )
}
