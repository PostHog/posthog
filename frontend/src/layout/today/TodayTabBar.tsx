import { MagnifyingGlassIcon } from '@phosphor-icons/react'
import { useActions, useValues } from 'kea'

import { cn } from '@posthog/quill'

import { commandLogic } from 'lib/components/Command/commandLogic'

import { TODAY_RAIL_ITEMS } from './todayRailItems'
import { todayShellLogic } from './todayShellLogic'

const TAB_CLASS =
    'flex min-w-0 flex-1 cursor-pointer flex-col items-center justify-center gap-0.5 rounded-md text-xxs font-medium outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-inset [&_svg]:size-5'

export function TodayTabBar(): JSX.Element {
    const { activePane } = useValues(todayShellLogic)
    const { pickPane } = useActions(todayShellLogic)
    const { toggleCommand } = useActions(commandLogic)

    return (
        <div className="TodayTabBar" data-quill>
            <nav aria-label="Main" className="flex h-14 min-w-0 flex-1 gap-1">
                {TODAY_RAIL_ITEMS.map(({ pane, label, Icon }) => {
                    const active = activePane === pane
                    return (
                        <button
                            key={pane}
                            type="button"
                            aria-current={active ? 'page' : undefined}
                            data-attr={`today-rail-${pane}`}
                            onClick={() => pickPane(pane)}
                            className={cn(
                                TAB_CLASS,
                                active ? 'bg-fill-selected text-foreground' : 'text-muted-foreground'
                            )}
                        >
                            <Icon weight={active ? 'fill' : 'regular'} />
                            <span className="max-w-full truncate">{label}</span>
                        </button>
                    )
                })}
                <button
                    type="button"
                    data-attr="today-rail-search"
                    onClick={() => toggleCommand('nav-search-button')}
                    className={cn(TAB_CLASS, 'text-muted-foreground')}
                >
                    <MagnifyingGlassIcon />
                    <span className="max-w-full truncate">Search</span>
                </button>
            </nav>
        </div>
    )
}
