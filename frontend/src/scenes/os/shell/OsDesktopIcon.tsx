import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'

import { GlassIcon } from './glass/GlassIcon'
import { GlassIconFromElement } from './glass/GlassIconFromElement'
import type { OsDesktopApp } from './osDesktopApps'
import type { OsWallpaperOption } from './osWallpapers'

export interface OsDesktopIconProps {
    app: OsDesktopApp
    wallpaper: OsWallpaperOption
    onOpen: (app: OsDesktopApp, from: Element, newWindow: boolean) => void
}

export function OsDesktopIcon({ app, wallpaper, onOpen }: OsDesktopIconProps): JSX.Element {
    const { icon } = app
    return (
        <li className="w-28 min-h-[84px] flex justify-center items-start">
            {/* Moves half a pixel on hover and press, like the posthog.com icons. Clicks are captured here,
                because the link stops Cmd and Ctrl clicks before its own click handler runs. */}
            <span
                className="relative inline-flex hover:top-[-0.5px] active:top-[0.5px]"
                onClickCapture={(event) => {
                    if (app.external) {
                        return
                    }
                    event.preventDefault()
                    onOpen(app, event.currentTarget, event.metaKey || event.ctrlKey)
                }}
                onAuxClick={(event) => {
                    if (app.external || event.button !== 1) {
                        return
                    }
                    event.preventDefault()
                    onOpen(app, event.currentTarget, true)
                }}
            >
                <LinkPrimitive
                    to={app.href}
                    target={app.external ? '_blank' : undefined}
                    className="group inline-flex flex-col items-center justify-center gap-0.5 max-w-28 text-center select-none text-white font-medium drop-shadow-lg rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white focus-visible:ring-2 focus-visible:ring-black/60"
                    data-attr={`os-desktop-icon-${app.key}`}
                >
                    {/* An inline wrapper, as on posthog.com, so the line box spaces the label the same way. */}
                    <span className="relative">
                        {icon.kind === 'glyph' ? (
                            <GlassIcon
                                path={icon.path}
                                viewBox={icon.viewBox}
                                fillRule={icon.fillRule}
                                glowColor={wallpaper.glow.light}
                                glowColorDark={wallpaper.glow.dark}
                            />
                        ) : (
                            <GlassIconFromElement
                                icon={icon.element}
                                glowColor={wallpaper.glow.light}
                                glowColorDark={wallpaper.glow.dark}
                            />
                        )}
                    </span>
                    <span className="text-[13px] font-medium leading-tight text-balance">
                        <span
                            className={cn(
                                'OsShell__icon-label inline-block rounded-[2px] px-0.5',
                                wallpaper.labelBackdrop && 'bg-black/50 dark:bg-black/60'
                            )}
                        >
                            {app.label}
                        </span>
                    </span>
                </LinkPrimitive>
            </span>
        </li>
    )
}
