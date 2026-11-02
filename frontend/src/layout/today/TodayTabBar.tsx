import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import { cn } from '@posthog/quill'

import { commandLogic } from 'lib/components/Command/commandLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { TodayNotificationsTab } from './TodayNotificationsTab'
import { TODAY_PANES, TODAY_RAIL_PANES } from './todayRailItems'
import { todayShellLogic } from './todayShellLogic'

const TAB_CLASS =
    'flex min-w-0 flex-1 cursor-pointer flex-col items-center justify-center gap-0.5 rounded-md text-xxs font-medium outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-inset [&_svg]:size-5'

export function TodayTabBar(): JSX.Element {
    const { activePane } = useValues(todayShellLogic)
    const { clickRailPane } = useActions(todayShellLogic)
    const { toggleCommand } = useActions(commandLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <div className="TodayTabBar" data-quill>
            <nav aria-label="Main" className="flex h-14 min-w-0 flex-1 gap-1">
                {TODAY_RAIL_PANES.map((pane) => {
                    const { label, icon } = TODAY_PANES[pane]
                    const active = activePane === pane
                    return (
                        <button
                            key={pane}
                            type="button"
                            aria-current={active ? 'page' : undefined}
                            data-attr={`today-rail-${pane}`}
                            onClick={() => clickRailPane(pane)}
                            className={cn(
                                TAB_CLASS,
                                active ? 'bg-fill-selected text-foreground' : 'text-muted-foreground'
                            )}
                        >
                            {icon}
                            <span className="max-w-full truncate">{label}</span>
                        </button>
                    )
                })}
                {featureFlags[FEATURE_FLAGS.REAL_TIME_NOTIFICATIONS] && (
                    <TodayNotificationsTab
                        active={activePane === 'notifications'}
                        onClick={() => clickRailPane('notifications')}
                        className={TAB_CLASS}
                    />
                )}
                <button
                    type="button"
                    data-attr="today-rail-search"
                    onClick={() => toggleCommand('nav-search-button')}
                    className={cn(TAB_CLASS, 'text-muted-foreground')}
                >
                    <IconSearch />
                    <span className="max-w-full truncate">Search</span>
                </button>
            </nav>
        </div>
    )
}
