import './TileActions.css'

import clsx from 'clsx'
import type { ReactNode } from 'react'

import { CardAction } from '@posthog/quill'

import { TileContextMenuButton } from './TileContextMenu'

/** The buttons at the end of a tile's or a section's header, followed by its menu button. */
export function TileActions({
    menu,
    alwaysVisible = false,
    className,
    children,
}: {
    menu: boolean
    /** Left false, the actions show only while the tile is under the pointer, so a big dashboard stays quiet. */
    alwaysVisible?: boolean
    className?: string
    children?: ReactNode
}): JSX.Element {
    return (
        <CardAction
            className={clsx('TileActions flex items-center gap-1', !alwaysVisible && 'TileActions--hover', className)}
        >
            {children}
            {menu && <TileContextMenuButton />}
        </CardAction>
    )
}
