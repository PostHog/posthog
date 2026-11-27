import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { getAppContext } from 'lib/utils/getAppContext'

import { todayDesignChangelogLogic } from './todayDesignChangelogLogic'
import { TodayMoreMenuRow } from './TodayMoreMenuRow'
import { todayRailLayoutLogic } from './todayRailLayoutLogic'
import { TodayRailTile } from './TodayRailTile'
import { TodayRailPane, todayShellLogic } from './todayShellLogic'

/** The panes that do not fit the rail and the ones the person hid from it, plus the way to arrange the rail. */
export function TodayMoreMenu({ overflowPanes }: { overflowPanes: TodayRailPane[] }): JSX.Element {
    const { activePane } = useValues(todayShellLogic)
    const { hiddenRailPanes, moreMenuOpen } = useValues(todayRailLayoutLogic)
    const { setCustomizeOpen, setMoreMenuOpen } = useActions(todayRailLayoutLogic)
    const { showChangelogAgain } = useActions(todayDesignChangelogLogic)
    const panes = [...overflowPanes, ...hiddenRailPanes]

    return (
        // Its open state lives in the logic, so the design changelog's demo can open it.
        <DropdownMenu open={moreMenuOpen} onOpenChange={setMoreMenuOpen}>
            <DropdownMenuTrigger
                render={
                    <TodayRailTile
                        label="More"
                        icon={<IconEllipsis />}
                        active={moreMenuOpen || panes.includes(activePane)}
                        // pinned: autocapture `data-attr` kept from when this menu was the help menu.
                        dataAttr="help-menu-button"
                    />
                }
            />
            <DropdownMenuContent side="right" align="end" className="w-72">
                {panes.length > 0 && (
                    <>
                        <DropdownMenuGroup>
                            <DropdownMenuLabel>More</DropdownMenuLabel>
                            {panes.map((pane) => (
                                <TodayMoreMenuRow key={pane} pane={pane} />
                            ))}
                        </DropdownMenuGroup>
                        <DropdownMenuSeparator />
                    </>
                )}
                <DropdownMenuItem data-attr="today-rail-customize" onClick={() => setCustomizeOpen(true)}>
                    Customize navigation
                </DropdownMenuItem>
                {getAppContext()?.preflight?.is_debug && (
                    <DropdownMenuItem onClick={showChangelogAgain}>Show design changelog</DropdownMenuItem>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
