import { ReactNode } from 'react'

import { IconEye, IconHide, IconTarget } from '@posthog/icons'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
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

export interface ChartLegendSeriesMenuProps {
    /** The series the menu acts on. Shown in the menu header so the target is never ambiguous —
     *  legend rows sit close together and a right-click can easily land on the neighbor. */
    seriesLabel: string
    seriesColor: string
    isHidden: boolean
    /** This series is the only visible one, so isolating it again restores every series. */
    isOnlyVisible: boolean
    areAllVisible: boolean
    /** False for a single-series legend, where isolating and hiding everything mean nothing. */
    canIsolate: boolean
    onToggle: () => void
    onIsolate: () => void
    onToggleAll: () => void
    /** Advertise the click gestures that reach these actions without the menu. Only true for the
     *  in-chart quill legend — the legend table's rows are checkboxes with no isolate gesture. */
    showGestureHints?: boolean
    children: ReactNode
}

/** Right-click menu for one chart legend row: isolate this series, toggle it, or toggle all of
 *  them. Styled to match the charts' own floating panels (popover surface, 12px text, tight radius)
 *  rather than the app's larger menus, so it reads as part of the chart it hangs off.
 *
 *  Purely presentational — the caller owns what each action does, and hands over the visibility
 *  state the labels switch on. */
export function ChartLegendSeriesMenu({
    seriesLabel,
    seriesColor,
    isHidden,
    isOnlyVisible,
    areAllVisible,
    canIsolate,
    onToggle,
    onIsolate,
    onToggleAll,
    showGestureHints = false,
    children,
}: ChartLegendSeriesMenuProps): JSX.Element {
    // Hiding all series is offered as its counterpart, "show all", once anything is hidden — but an
    // isolated row already offers exactly that above, so the row would just repeat itself.
    const showToggleAll = canIsolate && !isOnlyVisible

    return (
        <ContextMenu>
            <Tooltip
                title={<ChartLegendSeriesMenuHint canIsolate={canIsolate} showGestureHints={showGestureHints} />}
                delayMs={500}
            >
                <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
            </Tooltip>
            <ContextMenuContent className="click-outside-block w-fit max-w-[260px] min-w-[180px] rounded-sm bg-surface-popover text-xs">
                <div className="flex items-center gap-1.5 px-2 pt-1.5 pb-1 text-xs">
                    <span
                        aria-hidden="true"
                        // eslint-disable-next-line react/forbid-dom-props -- the swatch takes the series' own color
                        style={{ backgroundColor: seriesColor }}
                        className="size-2.5 shrink-0 rounded-sm"
                    />
                    <span className="truncate font-semibold" title={seriesLabel}>
                        {seriesLabel}
                    </span>
                </div>
                {/* The separator's default -mx-1 assumes a padded menu; here it overflows instead,
                    which makes ScrollableShadows paint a scroll shadow down the right edge. */}
                <ContextMenuSeparator className="mx-0" />
                <ContextMenuGroup>
                    {canIsolate && (
                        <ContextMenuItem asChild>
                            <ButtonPrimitive
                                menuItem
                                size="xs"
                                className="text-xs"
                                onClick={onIsolate}
                                data-attr="insight-legend-hide-other-series"
                            >
                                <IconTarget />
                                {isOnlyVisible ? 'Show all series' : 'Show only this series'}
                                {showGestureHints && <MenuItemGesture>click</MenuItemGesture>}
                            </ButtonPrimitive>
                        </ContextMenuItem>
                    )}
                    <ContextMenuItem asChild>
                        <ButtonPrimitive
                            menuItem
                            size="xs"
                            className="text-xs"
                            onClick={onToggle}
                            data-attr="insight-legend-toggle-series"
                        >
                            {isHidden ? <IconEye /> : <IconHide />}
                            {isHidden ? 'Show this series' : 'Hide this series'}
                            {showGestureHints && canIsolate && (
                                <MenuItemGesture>
                                    <KeyboardShortcut command minimal />
                                    click
                                </MenuItemGesture>
                            )}
                        </ButtonPrimitive>
                    </ContextMenuItem>
                    {showToggleAll && (
                        <ContextMenuItem asChild>
                            <ButtonPrimitive
                                menuItem
                                size="xs"
                                className="text-xs"
                                onClick={onToggleAll}
                                data-attr="insight-legend-toggle-all-series"
                            >
                                {areAllVisible ? <IconHide /> : <IconEye />}
                                {areAllVisible ? 'Hide all series' : 'Show all series'}
                            </ButtonPrimitive>
                        </ContextMenuItem>
                    )}
                </ContextMenuGroup>
            </ContextMenuContent>
        </ContextMenu>
    )
}

/** Right-aligned muted note showing the gesture that runs a menu item, so the menu teaches the
 *  click shortcuts instead of being the only way to reach them. */
function MenuItemGesture({ children }: { children: ReactNode }): JSX.Element {
    return (
        <span
            className="ml-auto flex shrink-0 items-center gap-0.5 pl-2 text-secondary"
            data-attr="chart-legend-menu-gesture"
        >
            {children}
        </span>
    )
}

function ChartLegendSeriesMenuHint({
    canIsolate,
    showGestureHints,
}: {
    canIsolate: boolean
    showGestureHints: boolean
}): JSX.Element {
    if (!showGestureHints) {
        return <>Right-click for options.</>
    }
    if (!canIsolate) {
        return <>Click to hide this series. Right-click for options.</>
    }
    return (
        <>
            Click to show only this series, <KeyboardShortcut command minimal />
            -click to add more. Right-click for options.
        </>
    )
}
