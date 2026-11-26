import { useValues } from 'kea'
import { useState } from 'react'

import { IconEllipsis } from '@posthog/icons'
import { Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { TodayRailTile } from './TodayRailTile'
import { TODAY_RAIL_WIDTH, TodayRailPane, todayShellLogic } from './todayShellLogic'

/** The rail panes that do not fit, as the rail's own tiles so a pane looks and behaves alike wherever it sits. */
export function TodayMoreMenu({
    overflowPanes,
    renderTile,
}: {
    overflowPanes: TodayRailPane[]
    renderTile: (pane: TodayRailPane) => JSX.Element
}): JSX.Element | null {
    const { activePane } = useValues(todayShellLogic)
    const [open, setOpen] = useState(false)

    if (overflowPanes.length === 0) {
        return null
    }

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger
                render={
                    <TodayRailTile
                        label="More"
                        icon={<IconEllipsis />}
                        active={open || overflowPanes.includes(activePane)}
                        // pinned: autocapture `data-attr` kept from when this menu was the help menu.
                        dataAttr="help-menu-button"
                    />
                }
            />
            <PopoverContent side="right" align="end" className="w-auto p-0 py-3">
                <div
                    className="flex flex-col items-center gap-3"
                    // The rail's width, so each tile takes the size it has on the rail.
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: TODAY_RAIL_WIDTH }}
                    onClickCapture={() => setOpen(false)}
                >
                    {overflowPanes.map(renderTile)}
                </div>
            </PopoverContent>
        </Popover>
    )
}
