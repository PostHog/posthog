import { ReactNode } from 'react'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    ContextMenu,
    ContextMenuContent,
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuSeparator,
    ContextMenuTrigger,
} from 'lib/ui/ContextMenu/ContextMenu'

export type InsightLegendRowContextMenuProps = {
    children: ReactNode
    areAllSeriesVisible: boolean
    showLegendIsolateSeriesItem: boolean
    isHidden: boolean
    isOnlyThisVisible: boolean
    onToggleOtherSeries: () => void
    onToggleAllSeries: () => void
}

export function InsightLegendRowContextMenu({
    children,
    areAllSeriesVisible,
    showLegendIsolateSeriesItem,
    isHidden,
    isOnlyThisVisible,
    onToggleOtherSeries,
    onToggleAllSeries,
}: InsightLegendRowContextMenuProps): JSX.Element {
    return (
        <ContextMenu>
            <Tooltip title="Right-click for options" delayMs={200}>
                <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
            </Tooltip>
            <ContextMenuContent className="max-w-[300px] click-outside-block">
                <ContextMenuGroup>
                    {showLegendIsolateSeriesItem && !isHidden && (
                        <ContextMenuItem asChild>
                            <ButtonPrimitive
                                menuItem
                                onClick={onToggleOtherSeries}
                                data-attr="insight-legend-hide-other-series"
                            >
                                {isOnlyThisVisible ? 'Show all series' : 'Hide other series'}
                            </ButtonPrimitive>
                        </ContextMenuItem>
                    )}
                    {showLegendIsolateSeriesItem && !isHidden && !isOnlyThisVisible && <ContextMenuSeparator />}
                    {!isOnlyThisVisible && (
                        <ContextMenuItem asChild>
                            <ButtonPrimitive
                                menuItem
                                onClick={onToggleAllSeries}
                                data-attr="insight-legend-toggle-all-series"
                            >
                                {areAllSeriesVisible ? 'Hide all series' : 'Show all series'}
                            </ButtonPrimitive>
                        </ContextMenuItem>
                    )}
                </ContextMenuGroup>
            </ContextMenuContent>
        </ContextMenu>
    )
}
