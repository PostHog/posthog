import './OsShell.scss'

import { useValues } from 'kea'

import { OsWindowLayer } from '../windows/OsWindowLayer'
import { OsDesktop } from './OsDesktop'
import { OsMenuBar } from './OsMenuBar'
import { osShellLogic } from './osShellLogic'

/**
 * The OS desktop that replaces the regular layout. Layers from the back: the desktop (wallpaper and
 * icons), the window layer, and the menu bar on top. The menu bar comes first in the DOM, so it is
 * the first thing the keyboard reaches.
 */
export function OsShell(): JSX.Element {
    const { wallpaper } = useValues(osShellLogic)

    return (
        <div className="OsShell" data-os-scheme="primary" data-os-wallpaper={wallpaper.key} data-attr="os-shell">
            <div className="relative z-1 flex flex-col h-full p-2 pointer-events-none">
                <div className="pointer-events-auto">
                    <OsMenuBar />
                </div>
                <div className="OsShell__window-layer flex flex-1 min-h-0 pt-2">
                    <OsWindowLayer />
                </div>
            </div>
            <OsDesktop />
        </div>
    )
}
