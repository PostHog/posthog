import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconClock } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuEmpty,
    DropdownMenuFilterProvider,
    DropdownMenuInput,
    DropdownMenuItem,
    DropdownMenuList,
    DropdownMenuTrigger,
    Skeleton,
} from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { TodayObjectIcon } from './TodayObjectIcon'
import { todayRecentsMenuLogic } from './todayRecentsMenuLogic'

/** A clock button joined to the search. It opens everything a person opened, from every rail pane, newest first. */
export function TodayTopBarRecents(): JSX.Element {
    const { menuItems, recentsHasLoaded } = useValues(todayRecentsMenuLogic)
    const { menuOpened, recentOpened } = useActions(todayRecentsMenuLogic)
    const [open, setOpen] = useState(false)

    return (
        <DropdownMenuFilterProvider autoHighlight>
            <DropdownMenu
                open={open}
                onOpenChange={(nextOpen) => {
                    setOpen(nextOpen)
                    if (nextOpen) {
                        menuOpened()
                    }
                }}
            >
                <DropdownMenuTrigger
                    render={
                        <Button
                            variant="outline"
                            size="icon"
                            aria-label="Recents"
                            // The menu covers the tooltip, so the tooltip stays off while the menu is open.
                            tooltip={open ? null : 'Recents'}
                            className="shrink-0 bg-[var(--today-paper)] text-muted-foreground hover:text-foreground data-[popup-open]:bg-[var(--fill-selected)]"
                            data-attr="today-top-bar-recents"
                        >
                            <IconClock />
                        </Button>
                    }
                />
                <DropdownMenuContent align="start" className="max-w-md">
                    {!recentsHasLoaded && menuItems.length === 0 ? (
                        <div className="flex flex-col gap-1 p-1" role="status" aria-label="Loading recents">
                            {[0, 1, 2].map((row) => (
                                <Skeleton key={row} className="h-7 w-64" />
                            ))}
                        </div>
                    ) : menuItems.length === 0 ? (
                        <p className="m-0 max-w-64 px-2 py-1.5 text-xs text-muted-foreground">
                            Anything you open, like a dashboard or a person, shows up here.
                        </p>
                    ) : (
                        <>
                            <DropdownMenuInput autoFocus placeholder="Search recents" aria-label="Search recents" />
                            <DropdownMenuEmpty>No recents match your search</DropdownMenuEmpty>
                            <DropdownMenuList>
                                {menuItems.map((item, index) => (
                                    <DropdownMenuItem
                                        key={item.href}
                                        label={`${item.name} ${item.typeLabel}`}
                                        onClick={() => recentOpened(item, index + 1)}
                                        data-attr="today-top-bar-recents-item"
                                    >
                                        <TodayObjectIcon type={item.iconType} className="shrink-0" />
                                        <span className="min-w-0 truncate">{item.name}</span>
                                        <span className="shrink-0 text-muted-foreground">{item.typeLabel}</span>
                                        <span className="ms-auto shrink-0 ps-4 text-xs text-muted-foreground">
                                            {item.viewedAt ? (
                                                <span translate="no">
                                                    <TZLabel time={item.viewedAt} showPopover={false} noStyles />
                                                </span>
                                            ) : null}
                                        </span>
                                    </DropdownMenuItem>
                                ))}
                            </DropdownMenuList>
                        </>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
        </DropdownMenuFilterProvider>
    )
}
