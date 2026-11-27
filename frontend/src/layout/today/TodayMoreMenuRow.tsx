import { useActions, useValues } from 'kea'

import { DropdownMenuItem, cn } from '@posthog/quill'

import { TODAY_PANE_INTROS } from './todayPaneIntros'
import { TODAY_PANES } from './todayRailItems'
import { TodayRailPane, todayShellLogic } from './todayShellLogic'

/** A rail pane as an item of the More menu, for a pane that does not fit the rail or that the person hid from it. */
export function TodayMoreMenuRow({ pane }: { pane: TodayRailPane }): JSX.Element {
    const { activePane } = useValues(todayShellLogic)
    // A pick, not the rail's click: a click on the open pane's tile hides the sidebar, and a menu pick never should.
    const { pickPane } = useActions(todayShellLogic)
    const active = activePane === pane

    return (
        <DropdownMenuItem
            description={TODAY_PANE_INTROS[pane].description}
            className={cn(active && 'bg-[var(--fill-selected)]')}
            aria-current={active ? 'page' : undefined}
            // pinned: matches the rail tile's data-attr, so a pick counts as the same pane wherever it sits.
            data-attr={`today-rail-${pane}`}
            onClick={() => pickPane(pane)}
        >
            {TODAY_PANES[pane].icon}
            {TODAY_PANES[pane].label}
        </DropdownMenuItem>
    )
}
