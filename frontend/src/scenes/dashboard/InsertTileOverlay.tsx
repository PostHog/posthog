import clsx from 'clsx'
import { useMemo, useState } from 'react'
import { Layout } from 'react-grid-layout'

import { IconPlusSmall } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu, LemonMenuItem } from 'lib/lemon-ui/LemonMenu'

interface InsertTileOverlayProps {
    /** The current breakpoint's tile layout (sm) — used to find the gaps between rows. */
    layout: Layout | undefined
    gridWidth: number
    rowHeight: number
    /** Vertical grid margin (px) — the gap between rows where the "+" affordance sits. */
    marginY: number
    canEditDashboard: boolean
    isMobileView: boolean
    /** Hide while a drag/resize gesture is in progress. */
    disabled?: boolean
    /** Builds the add-tile menu for an insertion at the given grid row. */
    getMenuItems: (targetY: number) => LemonMenuItem[]
}

/**
 * Overlays thin hover strips in the gaps between dashboard grid rows. Hovering a strip reveals a
 * "+" that opens the same add-tile menu as the header — but the new tile is inserted at that row
 * rather than appended at the bottom. Shown to anyone with edit access, in both view and edit mode.
 */
export function InsertTileOverlay({
    layout,
    gridWidth,
    rowHeight,
    marginY,
    canEditDashboard,
    isMobileView,
    disabled,
    getMenuItems,
}: InsertTileOverlayProps): JSX.Element | null {
    // Distinct row boundaries: the top (0), the start of every tile, and the bottom of the grid.
    const boundaryRows = useMemo(() => {
        const rows = new Set<number>([0])
        let maxBottom = 0
        for (const item of layout || []) {
            rows.add(item.y)
            maxBottom = Math.max(maxBottom, item.y + item.h)
        }
        rows.add(maxBottom)
        return Array.from(rows).sort((a, b) => a - b)
    }, [layout])

    if (!canEditDashboard || isMobileView || disabled) {
        return null
    }

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div className="absolute inset-0 pointer-events-none" style={{ zIndex: 6 }}>
            {boundaryRows.map((targetY) => (
                <InsertionStrip
                    key={targetY}
                    targetY={targetY}
                    // Center the strip on the gap above the tiles that start at this row.
                    topPx={Math.max(0, targetY * (rowHeight + marginY) - marginY / 2)}
                    gridWidth={gridWidth}
                    getMenuItems={getMenuItems}
                />
            ))}
        </div>
    )
}

const STRIP_HEIGHT = 16

function InsertionStrip({
    targetY,
    topPx,
    gridWidth,
    getMenuItems,
}: {
    targetY: number
    topPx: number
    gridWidth: number
    getMenuItems: (targetY: number) => LemonMenuItem[]
}): JSX.Element {
    const [menuOpen, setMenuOpen] = useState(false)

    const revealClass = menuOpen ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'

    return (
        <div
            className="group absolute pointer-events-auto"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ left: 0, width: gridWidth, top: topPx - STRIP_HEIGHT / 2, height: STRIP_HEIGHT }}
        >
            <div
                className={clsx(
                    'absolute left-0 right-0 top-1/2 -translate-y-1/2 h-px bg-accent transition-opacity',
                    revealClass
                )}
            />
            <div className={clsx('absolute left-0 top-1/2 -translate-y-1/2 transition-opacity', revealClass)}>
                <LemonMenu items={getMenuItems(targetY)} onVisibilityChange={setMenuOpen}>
                    <LemonButton
                        size="xsmall"
                        type="primary"
                        icon={<IconPlusSmall />}
                        data-attr="dashboard-inline-add-tile"
                        tooltip="Add a tile here"
                    />
                </LemonMenu>
            </div>
        </div>
    )
}
