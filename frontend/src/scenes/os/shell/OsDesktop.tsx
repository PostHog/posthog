import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    ContextMenu,
    ContextMenuContent,
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuLabel,
    ContextMenuSeparator,
    ContextMenuTrigger,
} from 'lib/ui/ContextMenu/ContextMenu'
import { urls } from 'scenes/urls'

import { OsDesktopIcon } from './OsDesktopIcon'
import { osShellLogic } from './osShellLogic'
import { OsWallpaper } from './OsWallpaper'
import { OS_WALLPAPERS } from './osWallpapers'

// The menu bar is 42px tall inside the shell's 8px padding. Icons start 16px below it.
const ICON_COLUMN_CLASS = 'list-none m-0 p-0 flex flex-col content-start h-[calc(100dvh-82px)]'

/** The wallpaper, the icon columns and the right-click menu. Windows render above it. */
export function OsDesktop(): JSX.Element {
    const { wallpaper, desktopColumns } = useValues(osShellLogic)
    const { setWallpaper, openApp } = useActions(osShellLogic)
    const onOpen = ({ href, label }: { href: string; label: string }, from?: Element, newWindow?: boolean): void => {
        // Windows zoom open from the icon, in the window layer's coordinates.
        const layer = document.querySelector('[data-attr="os-window-layer"]')?.getBoundingClientRect()
        const icon = from?.getBoundingClientRect()
        const origin =
            layer && icon
                ? { x: icon.left + icon.width / 2 - layer.left, y: icon.top + icon.height / 2 - layer.top }
                : undefined
        openApp(href, label, origin, newWindow)
    }

    return (
        <ContextMenu>
            <ContextMenuTrigger asChild>
                <div className="absolute inset-0 z-0" data-attr="os-desktop">
                    <OsWallpaper wallpaper={wallpaper.key} />
                    <nav aria-label="Desktop" className="relative flex justify-between items-start px-1 pt-[66px]">
                        <ul className={`${ICON_COLUMN_CLASS} flex-wrap`}>
                            {desktopColumns.left.map((app) => (
                                <OsDesktopIcon key={app.key} app={app} wallpaper={wallpaper} onOpen={onOpen} />
                            ))}
                        </ul>
                        {/* Wraps into new columns towards the middle, so the first column stays on the edge. */}
                        <ul className={`${ICON_COLUMN_CLASS} flex-wrap-reverse`}>
                            {desktopColumns.right.map((app) => (
                                <OsDesktopIcon key={app.key} app={app} wallpaper={wallpaper} onOpen={onOpen} />
                            ))}
                        </ul>
                    </nav>
                </div>
            </ContextMenuTrigger>
            <ContextMenuContent className="min-w-56">
                <ContextMenuGroup>
                    <ContextMenuLabel>Wallpaper</ContextMenuLabel>
                    {OS_WALLPAPERS.map(({ key, label }) => (
                        <ContextMenuItem key={key} asChild>
                            <ButtonPrimitive
                                menuItem
                                role="menuitemradio"
                                aria-checked={wallpaper.key === key}
                                active={wallpaper.key === key}
                                onClick={() => setWallpaper(key)}
                                data-attr={`os-wallpaper-${key}`}
                            >
                                <IconCheck className={wallpaper.key === key ? 'visible' : 'invisible'} />
                                {label}
                            </ButtonPrimitive>
                        </ContextMenuItem>
                    ))}
                </ContextMenuGroup>
                <ContextMenuSeparator />
                <ContextMenuGroup>
                    <ContextMenuItem asChild>
                        <ButtonPrimitive
                            menuItem
                            onClick={() => onOpen({ href: urls.settings('user-navigation'), label: 'Settings' })}
                            data-attr="os-desktop-customize-icons"
                        >
                            Choose desktop apps
                        </ButtonPrimitive>
                    </ContextMenuItem>
                </ContextMenuGroup>
            </ContextMenuContent>
        </ContextMenu>
    )
}
