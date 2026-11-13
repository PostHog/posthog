import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'

import { commandLogic } from 'lib/components/Command/commandLogic'

import { TodayMoreMenu } from './TodayMoreMenu'
import { TODAY_PANES } from './todayRailItems'
import { todayShellLogic } from './todayShellLogic'
import { TodayTabBarTab } from './TodayTabBarTab'

export function TodayTabBar(): JSX.Element {
    const { activePane, railPanes } = useValues(todayShellLogic)
    const { clickRailPane } = useActions(todayShellLogic)
    const { toggleCommand } = useActions(commandLogic)

    return (
        <div className="TodayTabBar" data-quill>
            <nav aria-label="Main" className="flex h-14 min-w-0 flex-1 gap-1">
                {railPanes.map((pane) => {
                    const active = activePane === pane
                    return (
                        <TodayTabBarTab
                            key={pane}
                            label={TODAY_PANES[pane].label}
                            icon={TODAY_PANES[pane].icon}
                            active={active}
                            aria-current={active ? 'page' : undefined}
                            dataAttr={`today-rail-${pane}`}
                            onClick={() => clickRailPane(pane)}
                        />
                    )
                })}
                <TodayTabBarTab
                    label="Search"
                    icon={<IconSearch />}
                    active={false}
                    dataAttr="today-rail-search"
                    onClick={() => toggleCommand('nav-search-button')}
                />
                <TodayMoreMenu placement="tab-bar" />
            </nav>
        </div>
    )
}
