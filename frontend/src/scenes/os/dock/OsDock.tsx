import './OsDock.scss'

import { useActions, useValues } from 'kea'
import { CSSProperties } from 'react'

import { IconBrowser, IconStore } from '@posthog/icons'

import { OsAppIcon } from '../store/OsAppIcon'
import type { OsPoint } from '../windows/osWindowGeometry'
import { osDockLogic } from './osDockLogic'
import { OsDockTile } from './OsDockTile'

// Windows zoom open from the dock tile, in the window layer's coordinates.
function originOf(from: Element): OsPoint | undefined {
    const layer = document.querySelector('[data-attr="os-window-layer"]')?.getBoundingClientRect()
    const tile = from.getBoundingClientRect()
    return layer ? { x: tile.left + tile.width / 2 - layer.left, y: tile.top + tile.height / 2 - layer.top } : undefined
}

export function OsDock(): JSX.Element {
    const { dock } = useValues(osDockLogic)
    const { activateWindow, openAppStore } = useActions(osDockLogic)

    return (
        <nav
            aria-label="Dock"
            className="order-last flex justify-center pt-2 pointer-events-none"
            data-os-scheme="primary"
            data-attr="os-dock"
        >
            <ul
                className="OsDock__shelf"
                // oxlint-disable-next-line react/forbid-dom-props
                style={{ '--os-dock-count': dock.windows.length + 2 } as CSSProperties}
            >
                <OsDockTile
                    label="App Store"
                    icon={
                        <span aria-hidden className="OsDock__icon OsDock__icon--store">
                            <IconStore />
                        </span>
                    }
                    open={!!dock.store.windowId}
                    focused={dock.store.focused}
                    minimized={dock.store.minimized}
                    onClick={(from) => openAppStore(originOf(from))}
                    data-attr="os-dock-app-store"
                />
                {dock.windows.length > 0 && <li className="OsDock__divider" aria-hidden />}
                {dock.windows.map((item) => (
                    <OsDockTile
                        key={item.windowId}
                        label={item.title}
                        icon={
                            <OsAppIcon
                                app={item.app ?? {}}
                                icon={item.app ? undefined : <IconBrowser />}
                                size="custom"
                                className="OsDock__icon"
                            />
                        }
                        open
                        focused={item.focused}
                        minimized={item.minimized}
                        onClick={() => activateWindow(item.windowId)}
                        data-attr="os-dock-window"
                    />
                ))}
            </ul>
        </nav>
    )
}
