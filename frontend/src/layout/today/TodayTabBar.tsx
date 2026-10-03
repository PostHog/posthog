import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import { Button, cn } from '@posthog/quill'

import { commandLogic } from 'lib/components/Command/commandLogic'

import { TODAY_TAB_BAR_ITEMS } from './todayRailItems'
import { TODAY_MORE_PANES, todayShellLogic } from './todayShellLogic'

/** The rail on phone-width windows: the panes in a bar across the bottom, with search beside them. */
export function TodayTabBar(): JSX.Element {
    const { activePane } = useValues(todayShellLogic)
    const { pickPane } = useActions(todayShellLogic)
    const { toggleCommand } = useActions(commandLogic)

    return (
        <div className="TodayTabBar" data-quill>
            <nav
                aria-label="Main"
                className="flex h-15 min-w-0 flex-1 rounded-full border border-[var(--border)] bg-[var(--card)] p-1 shadow-md"
            >
                {TODAY_TAB_BAR_ITEMS.map(({ pane, label, icon }) => {
                    const active = activePane === pane || (pane === 'more' && TODAY_MORE_PANES.includes(activePane))
                    return (
                        <button
                            key={pane}
                            type="button"
                            aria-current={active ? 'page' : undefined}
                            data-attr={`today-rail-${pane}`}
                            onClick={() => pickPane(pane)}
                            className={cn(
                                'flex min-w-0 flex-1 cursor-pointer flex-col items-center justify-center gap-0.5 rounded-full text-[11px] leading-3 font-medium outline-none',
                                'focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-inset [&_svg]:size-5.5',
                                active ? 'bg-[var(--fill-selected)] text-foreground' : 'text-muted-foreground'
                            )}
                        >
                            {icon}
                            <span className="max-w-full truncate">{label}</span>
                        </button>
                    )
                })}
            </nav>
            <Button
                variant="outline"
                size="icon-lg"
                aria-label="Search"
                data-attr="today-rail-search"
                onClick={() => toggleCommand('nav-search-button')}
                className="size-15 shrink-0 rounded-full bg-[var(--card)] shadow-md [&_svg]:size-5.5"
            >
                <IconSearch />
            </Button>
        </div>
    )
}
