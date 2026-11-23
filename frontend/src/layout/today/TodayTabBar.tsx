import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'

import { commandLogic } from 'lib/components/Command/commandLogic'

import { TodayPhoneMoreSheet } from './TodayPhoneMoreSheet'
import { todayPhoneTabsLogic } from './todayPhoneTabsLogic'
import { TODAY_PANES } from './todayRailItems'
import { TodayRailPane, todayShellLogic } from './todayShellLogic'
import { TodayTabBarTab } from './TodayTabBarTab'

export function TodayTabBar(): JSX.Element {
    const { activePane, sidebarVisible } = useValues(todayShellLogic)
    const { phoneTabPanes } = useValues(todayPhoneTabsLogic)
    const { clickRailPane } = useActions(todayShellLogic)
    const { isCommandOpen } = useValues(commandLogic)
    const { toggleCommand, closeCommand } = useActions(commandLogic)

    const selectPane = (pane: TodayRailPane): void => {
        if (isCommandOpen) {
            closeCommand()
            if (activePane === pane && sidebarVisible) {
                return
            }
        }
        clickRailPane(pane)
    }

    return (
        <div className="TodayTabBar" data-quill>
            <nav aria-label="Main" className="flex h-14 min-w-0 flex-1 gap-1">
                {phoneTabPanes.map((pane) => {
                    const active = !isCommandOpen && activePane === pane
                    return (
                        <TodayTabBarTab
                            key={pane}
                            label={TODAY_PANES[pane].label}
                            icon={TODAY_PANES[pane].icon}
                            active={active}
                            aria-current={active ? 'page' : undefined}
                            dataAttr={`today-rail-${pane}`}
                            onClick={() => selectPane(pane)}
                        />
                    )
                })}
                <TodayTabBarTab
                    label="Search"
                    icon={<IconSearch />}
                    active={isCommandOpen}
                    aria-current={isCommandOpen ? 'page' : undefined}
                    dataAttr="today-rail-search"
                    onClick={() => toggleCommand('nav-search-button')}
                />
                <TodayPhoneMoreSheet />
            </nav>
        </div>
    )
}
